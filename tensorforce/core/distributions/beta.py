# Copyright 2018 Tensorforce Team. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from math import log

import tensorflow as tf

from tensorforce import util
from tensorforce.core import layer_modules, Module
from tensorforce.core.distributions import Distribution


class Beta(Distribution):
    """
    Beta distribution, for bounded continuous actions (specification key: `beta`).

    Args:
        name (string): Distribution name
            (<span style="color:#0000C0"><b>internal use</b></span>).
        action_spec (specification): Action specification
            (<span style="color:#0000C0"><b>internal use</b></span>).
        embedding_size (int > 0): Embedding size
            (<span style="color:#0000C0"><b>internal use</b></span>).
        summary_labels ('all' | iter[string]): Labels of summaries to record
            (<span style="color:#00C000"><b>default</b></span>: inherit value of parent module).
    """

    def __init__(self, name, action_spec, embedding_size, summary_labels=None):
        super().__init__(
            name=name, action_spec=action_spec, embedding_size=embedding_size,
            summary_labels=summary_labels
        )

        action_size = util.product(xs=self.action_spec['shape'], empty=0)
        input_spec = dict(type='float', shape=(self.embedding_size,))
        self.alpha = self.add_module(
            name='alpha', module='linear', modules=layer_modules, size=action_size,
            input_spec=input_spec
        )
        self.beta = self.add_module(
            name='beta', module='linear', modules=layer_modules, size=action_size,
            input_spec=input_spec
        )

        Module.register_tensor(
            name=(self.name + '-alpha'), spec=dict(type='float', shape=self.action_spec['shape']),
            batched=True
        )
        Module.register_tensor(
            name=(self.name + '-beta'), spec=dict(type='float', shape=self.action_spec['shape']),
            batched=True
        )

    def tf_parametrize(self, x):
        # Softplus to ensure alpha and beta >= 1
        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))
        epsilon = tf.constant(value=util.epsilon, dtype=util.tf_dtype(dtype='float'))
        log_epsilon = tf.constant(value=log(util.epsilon), dtype=util.tf_dtype(dtype='float'))
        shape = (-1,) + self.action_spec['shape']

        # Alpha
        alpha = self.alpha.apply(x=x)
        # epsilon < 1.0, hence negative
        alpha = tf.clip_by_value(t=alpha, clip_value_min=log_epsilon, clip_value_max=-log_epsilon)
        alpha = tf.math.softplus(features=alpha) + one
        alpha = tf.reshape(tensor=alpha, shape=shape)

        # Beta
        beta = self.beta.apply(x=x)
        # epsilon < 1.0, hence negative
        beta = tf.clip_by_value(t=beta, clip_value_min=log_epsilon, clip_value_max=-log_epsilon)
        beta = tf.math.softplus(features=beta) + one
        beta = tf.reshape(tensor=beta, shape=shape)

        # Alpha + Beta
        alpha_beta = tf.maximum(x=(alpha + beta), y=epsilon)

        # Log norm
        log_norm = tf.lgamma(x=alpha) + tf.lgamma(x=beta) - tf.lgamma(x=alpha_beta)

        Module.update_tensor(name=(self.name + '-alpha'), tensor=alpha)
        Module.update_tensor(name=(self.name + '-beta'), tensor=beta)
        alpha, alpha_beta, log_norm = self.add_summary(
            label=('distributions', 'beta'), name='alpha', tensor=alpha,
            pass_tensors=(alpha, alpha_beta, log_norm)
        )
        beta, alpha_beta, log_norm = self.add_summary(
            label=('distributions', 'beta'), name='beta', tensor=beta,
            pass_tensors=(beta, alpha_beta, log_norm)
        )

        return alpha, beta, alpha_beta, log_norm

    def tf_sample(self, parameters, deterministic):
        alpha, beta, alpha_beta, _ = parameters

        # Deterministic: mean as action
        definite = beta / alpha_beta

        # Non-deterministic: sample action using gamma distribution
        alpha_sample = tf.random_gamma(shape=(), alpha=alpha, dtype=util.tf_dtype(dtype='float'))
        beta_sample = tf.random_gamma(shape=(), alpha=beta, dtype=util.tf_dtype(dtype='float'))

        epsilon = tf.constant(value=util.epsilon, dtype=util.tf_dtype(dtype='float'))

        sampled = beta_sample / tf.maximum(x=(alpha_sample + beta_sample), y=epsilon)

        sampled = tf.where(condition=deterministic, x=definite, y=sampled)

        min_value = tf.constant(
            value=self.action_spec['min_value'], dtype=util.tf_dtype(dtype='float')
        )
        max_value = tf.constant(
            value=self.action_spec['max_value'], dtype=util.tf_dtype(dtype='float')
        )

        return min_value + (max_value - min_value) * sampled

    def tf_log_probability(self, parameters, action):
        alpha, beta, _, log_norm = parameters

        min_value = tf.constant(
            value=self.action_spec['min_value'], dtype=util.tf_dtype(dtype='float')
        )
        max_value = tf.constant(
            value=self.action_spec['max_value'], dtype=util.tf_dtype(dtype='float')
        )

        action = (action - min_value) / (max_value - min_value)

        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))
        epsilon = tf.constant(value=util.epsilon, dtype=util.tf_dtype(dtype='float'))

        action = tf.minimum(x=action, y=(one - epsilon))

        return tf.math.xlogy(x=(beta - one), y=tf.maximum(x=action, y=epsilon)) + \
            (alpha - one) * tf.log1p(x=(-action)) - log_norm

    def tf_entropy(self, parameters):
        alpha, beta, alpha_beta, log_norm = parameters

        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))

        if util.tf_dtype(dtype='float') in (tf.float32, tf.float64):
            digamma_alpha = tf.digamma(x=alpha)
            digamma_beta = tf.digamma(x=beta)
            digamma_alpha_beta = tf.digamma(x=alpha_beta)
        else:
            digamma_alpha = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=alpha, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )
            digamma_beta = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=beta, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )
            digamma_alpha_beta = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=alpha_beta, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )

        return log_norm - (beta - one) * digamma_beta - (alpha - one) * digamma_alpha + \
            (alpha_beta - one - one) * digamma_alpha_beta

    def tf_kl_divergence(self, parameters1, parameters2):
        alpha1, beta1, alpha_beta1, log_norm1 = parameters1
        alpha2, beta2, alpha_beta2, log_norm2 = parameters2

        if util.tf_dtype(dtype='float') in (tf.float32, tf.float64):
            digamma_alpha1 = tf.digamma(x=alpha1)
            digamma_beta1 = tf.digamma(x=beta1)
            digamma_alpha_beta1 = tf.digamma(x=alpha_beta1)
        else:
            digamma_alpha1 = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=alpha1, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )
            digamma_beta1 = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=beta1, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )
            digamma_alpha_beta1 = tf.dtypes.cast(
                x=tf.digamma(x=tf.dtypes.cast(x=alpha_beta1, dtype=tf.float32)),
                dtype=util.tf_dtype(dtype='float')
            )

        return log_norm2 - log_norm1 - digamma_beta1 * (beta2 - beta1) - \
            digamma_alpha1 * (alpha2 - alpha1) + digamma_alpha_beta1 * \
            (alpha_beta2 - alpha_beta1)
