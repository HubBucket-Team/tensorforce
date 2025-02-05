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

import tensorflow as tf

from tensorforce import util
from tensorforce.core import layer_modules, Module
from tensorforce.core.distributions import Distribution


class Bernoulli(Distribution):
    """
    Bernoulli distribution, for binary boolean actions (specification key: `bernoulli`).

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
        self.logit = self.add_module(
            name='logit', module='linear', modules=layer_modules, size=action_size,
            input_spec=input_spec
        )

        Module.register_tensor(
            name=(self.name + '-probability'),
            spec=dict(type='float', shape=self.action_spec['shape']), batched=True
        )

    def tf_parametrize(self, x):
        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))
        epsilon = tf.constant(value=util.epsilon, dtype=util.tf_dtype(dtype='float'))
        shape = (-1,) + self.action_spec['shape']

        # Logit
        logit = self.logit.apply(x=x)
        logit = tf.reshape(tensor=logit, shape=shape)

        # States value
        states_value = logit

        # Sigmoid for corresponding probability
        probability = tf.sigmoid(x=logit)

        # Clip probability for numerical stability
        probability = tf.clip_by_value(
            t=probability, clip_value_min=epsilon, clip_value_max=(one - epsilon)
        )

        # "Normalized" logits
        true_logit = tf.log(x=probability)
        false_logit = tf.log(x=(one - probability))

        Module.update_tensor(name=(self.name + '-probability'), tensor=probability)
        true_logit, false_logit, probability, states_value = self.add_summary(
            label=('distributions', 'bernoulli'), name='probability', tensor=probability,
            pass_tensors=(true_logit, false_logit, probability, states_value)
        )

        return true_logit, false_logit, probability, states_value

    def tf_sample(self, parameters, deterministic):
        _, _, probability, _ = parameters

        half = tf.constant(value=0.5, dtype=util.tf_dtype(dtype='float'))

        # Deterministic: true if >= 0.5
        definite = tf.greater_equal(x=probability, y=half)

        # Non-deterministic: sample true if >= uniform distribution
        uniform = tf.random.uniform(
            shape=tf.shape(input=probability), dtype=util.tf_dtype(dtype='float')
        )
        sampled = tf.greater_equal(x=probability, y=uniform)

        return tf.where(condition=deterministic, x=definite, y=sampled)

    def tf_log_probability(self, parameters, action):
        true_logit, false_logit, _, _ = parameters

        return tf.where(condition=action, x=true_logit, y=false_logit)

    def tf_entropy(self, parameters):
        true_logit, false_logit, probability, _ = parameters

        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))

        return -probability * true_logit - (one - probability) * false_logit

    def tf_kl_divergence(self, parameters1, parameters2):
        true_logit1, false_logit1, probability1, _ = parameters1
        true_logit2, false_logit2, _, _ = parameters2

        true_log_prob_ratio = true_logit1 - true_logit2
        false_log_prob_ratio = false_logit1 - false_logit2

        one = tf.constant(value=1.0, dtype=util.tf_dtype(dtype='float'))

        return probability1 * true_log_prob_ratio + (one - probability1) * false_log_prob_ratio

    def tf_action_value(self, parameters, action=None):
        true_logit, false_logit, _, states_value = parameters

        if action is None:
            states_value = tf.expand_dims(input=states_value, axis=-1)
            logits = tf.stack(values=(false_logit, true_logit), axis=-1)

        else:
            logits = tf.where(condition=action, x=true_logit, y=false_logit)

        return states_value + logits

    def tf_states_value(self, parameters):
        _, _, _, states_value = parameters

        return states_value
