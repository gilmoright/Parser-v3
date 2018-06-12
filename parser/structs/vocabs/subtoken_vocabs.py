#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# Copyright 2017 Timothy Dozat
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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import codecs
from collections import Counter

import numpy as np
import tensorflow as tf

from parser.structs.buckets import ListMultibucket
from .base_vocabs import CountVocab
from . import conllu_vocabs as cv

from parser.neural import nn, nonlin, embeddings, recurrent, classifiers

#***************************************************************
class SubtokenVocab(CountVocab):
  """"""
  
  #=============================================================
  def __init__(self, config=None):
    """"""
    
    super(SubtokenVocab, self).__init__(config=config)
    self._multibucket = ListMultibucket(self, max_buckets=self.max_buckets, config=config)
    self._tok2idx = {}
    self._idx2tok = {}
    return
  
  #=============================================================
  def get_input_tensor(self, embed_keep_prob=None, nonzero_init=False, variable_scope=None, reuse=True):
    """"""
    
    embed_keep_prob = embed_keep_prob or self.embed_keep_prob
    conv_keep_prob = 1. if reuse else self.conv_keep_prob
    recur_keep_prob = 1. if reuse else self.recur_keep_prob
    linear_keep_prob = 1. if reuse else self.linear_keep_prob
    
    layers = []
    with tf.variable_scope(variable_scope or self.field) as scope:
      for i, placeholder in enumerate(self._multibucket.get_placeholders()):
        if i:
          scope.reuse_variables()
        with tf.variable_scope('Embeddings'):
          layer = embeddings.token_embedding_lookup(len(self), self.embed_size,
                                                     placeholder,
                                                     nonzero_init=nonzero_init,
                                                     reuse=reuse)
        
        seq_lengths = tf.count_nonzero(placeholder, axis=1)
        for j in xrange(self.n_layers):
          conv_width = self.first_layer_conv_width if not j else self.conv_width
          with tf.variable_scope('RNN-{}'.format(j)):
            layer, final_states = recurrent.directed_RNN(
              layer, self.recur_size, seq_lengths,
              bidirectional=self.bidirectional,
              recur_cell=self.recur_cell,
              conv_width=conv_width,
              recur_func=self.recur_func,
              conv_keep_prob=conv_keep_prob,
              recur_keep_prob=recur_keep_prob,
              drop_type=self.drop_type,
              cifg=self.cifg,
              nog=self.nog)
        
        if self.squeeze_type == 'linear_attention':
          with tf.variable_scope('Attention'):
            layer = classifiers.linear_attention(layer, hidden_keep_prob=linear_keep_prob)[1]
        elif self.squeeze_type == 'final_hidden':
          layer, _ = tf.split(final_states, 2, axis=-1)
        elif self.squeeze_type == 'final_cell':
          _, layer = tf.split(final_states, 2, axis=-1)
        elif self.squeeze_type == 'final_state':
          layer = final_states
          
        with tf.variable_scope('Linear'):
          layer = classifiers.hidden(layer, self.linear_size,
                                     hidden_func=tf.identity,
                                     hidden_keep_prob=linear_keep_prob)
        layers.append(layer)
      # Concatenate all the buckets' embeddings
      layer = tf.concat(layers, 0)
      # Put them in the right order, creating the embedding matrix
      layer = tf.gather(layer, self._multibucket.placeholder)
      # Get the embeddings from the embedding matrix
      layer = tf.nn.embedding_lookup(layer, self.placeholder)
    
      if embed_keep_prob < 1:
        layer = self.drop_func(layer, embed_keep_prob)
    return layer
  
  #=============================================================
  def count(self, train_conllus):
    """"""
    
    tokens = set()
    for train_conllu in train_conllus:
      with codecs.open(train_conllu, encoding='utf-8', errors='ignore') as f:
        for line in f:
          line = line.strip()
          if line and not line.startswith('#'):
            line = line.split('\t')
            token = line[self.conllu_idx] # conllu_idx is provided by the CoNLLUVocab
            if token not in tokens:
              tokens.add(token)
              self._count(token)
    self.index_by_counts()
    return True
  
  def _count(self, token):
    if not self.cased:
      token = token.lower()
    self.counts.update(token)
    return
  
  #=============================================================
  def add(self, token):
    """"""
    
    characters = list(token)
    character_indices = [self._str2idx.get(character, self.UNK_IDX) for character in characters]
    token_index = self._multibucket.add(character_indices, characters)
    self._tok2idx[token] = token_index
    self._idx2tok[token_index] = token
    return token_index
  
  #=============================================================
  def token(self, index):
    """"""
    
    return self._idx2tok[index]
  
  #=============================================================
  def index(self, token):
    """"""
    
    return self._tok2idx[token]
  
  #=============================================================
  def set_placeholders(self, indices, feed_dict={}):
    """"""
    
    unique_indices, inverse_indices = np.unique(indices, return_inverse=True)
    feed_dict[self.placeholder] = inverse_indices.reshape(indices.shape)
    self._multibucket.set_placeholders(unique_indices, feed_dict=feed_dict)
    return
    
  #=============================================================
  def open(self):
    """"""
    
    self._multibucket.open()
    return self
  
  #=============================================================
  def close(self):
    """"""
    
    self._multibucket.close()
    return
  
  #=============================================================
  def reset(self):
    """"""
    
    self._idx2tok = {}
    self._tok2idx = {}
    self._multibucket.reset()
  
  #=============================================================
  @property
  def filename(self):
    return os.path.join(self._config.getstr(self, 'save_dir'), self.field+'-subtokens.lst')
  @property
  def max_buckets(self):
    return self._config.getint(self, 'max_buckets')
  @property
  def embed_keep_prob(self):
    return self._config.getfloat(self, 'embed_keep_prob')
  @property
  def conv_keep_prob(self):
    return self._config.getfloat(self, 'conv_keep_prob')
  @property
  def recur_keep_prob(self):
    return self._config.getfloat(self, 'recur_keep_prob')
  @property
  def linear_keep_prob(self):
    return self._config.getfloat(self, 'linear_keep_prob')
  @property
  def hidden_keep_prob(self):
    return self._config.getfloat(self, 'hidden_keep_prob')
  @property
  def n_layers(self):
    return self._config.getint(self, 'n_layers')
  @property
  def first_layer_conv_width(self):
    return self._config.getint(self, 'first_layer_conv_width')
  @property
  def conv_width(self):
    return self._config.getint(self, 'conv_width')
  @property
  def embed_size(self):
    return self._config.getint(self, 'embed_size')
  @property
  def recur_size(self):
    return self._config.getint(self, 'recur_size')
  @property
  def linear_size(self):
    return self._config.getint(self, 'linear_size')
  @property
  def hidden_size(self):
    return self._config.getint(self, 'hidden_size')
  @property
  def bidirectional(self):
    return self._config.getboolean(self, 'bidirectional')
  @property
  def drop_func(self):
    drop_func = self._config.getstr(self, 'drop_func')
    if hasattr(embeddings, drop_func):
      return getattr(embeddings, drop_func)
    else:
      raise AttributeError("module '{}' has no attribute '{}'".format(embeddings.__name__, drop_func))
  @property
  def recur_func(self):
    recur_func = self._config.getstr(self, 'recur_func')
    if hasattr(nonlin, recur_func):
      return getattr(nonlin, recur_func)
    else:
      raise AttributeError("module '{}' has no attribute '{}'".format(nonlin.__name__, recur_func))
  @property
  def recur_cell(self):
    recur_cell = self._config.getstr(self, 'recur_cell')
    if hasattr(recurrent, recur_cell):
      return getattr(recurrent, recur_cell)
    else:
      raise AttributeError("module '{}' has no attribute '{}'".format(recurrent.__name__, recur_func))
  @property
  def drop_type(self):
    return self._config.getstr(self, 'drop_type')
  @property
  def cifg(self):
    return self._config.getboolean(self, 'cifg')
  @property
  def nog(self):
    return self._config.getboolean(self, 'nog')
  @property
  def squeeze_type(self):
    return self._config.getstr(self, 'squeeze_type')

#***************************************************************
class GraphSubtokenVocab(SubtokenVocab):
  """"""
  
  def _collect_tokens(self, node):
    node = node.split('|')
    for edge in node:
      edge = edge.split(':', 1)
      head, rel = edge
      self.counts.update(rel)

#***************************************************************
class FormSubtokenVocab(SubtokenVocab, cv.FormVocab):
  pass
class LemmaSubtokenVocab(SubtokenVocab, cv.LemmaVocab):
  pass
class UPOSSubtokenVocab(SubtokenVocab, cv.UPOSVocab):
  pass
class XPOSSubtokenVocab(SubtokenVocab, cv.XPOSVocab):
  pass
class DeprelSubtokenVocab(SubtokenVocab, cv.DeprelVocab):
  pass
