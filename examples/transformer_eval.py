"""
Example pipeline. This is a minimal example of basic RNN language model.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# pylint: disable=invalid-name, no-name-in-module

import tensorflow as tf
# from tensorflow.python.framework import ops

# We shall wrap all these modules
from txtgen.data import database
from txtgen.modules import ConstantConnector
from txtgen.modules import TransformerEncoder, TransformerDecoder
from txtgen.losses import mle_losses
from txtgen.core import optimization as opt
from txtgen import context
import os
import codecs
if __name__ == "__main__":
    ### Build data pipeline

    # Config data hyperparams. Hyperparams not configured will be automatically
    # filled with default values. For text database, default values are defined
    # in `txtgen.data.database.default_text_dataset_hparams()`.
    data_hparams = {
        "num_epochs": 1,
        "seed": 123,
        "batch_size":32,
        "source_dataset": {
            "files": ['data/translation/de-en/de_sentences.txt'],
            "vocab_file": 'data/translation/de-en/de.vocab.txt',
            "processing":{
                "bos_token": "<SOURCE_BOS>",
                "eos_token": "<SOURCE_EOS>",
                }
        },
        "target_dataset": {
            "files": ['data/translation/de-en/en_sentences.txt'],
            "vocab_file": 'data/translation/de-en/en.vocab.txt',
            # "reader_share": True,
            "processing":{
                "bos_token": "<TARGET_BOS>",
                "eos_token": "<TARGET_EOS>",
            },
        }
    }
    extra_hparams = {
        'max_seq_length':10,
        'scale':True,
        'sinusoid':True,
        'embedding': {
            'dim': 512,
        },
        'num_blocks': 6,
        'num_heads': 8,
    }
    # Construct the database
    text_database = database.PairedTextDataBase(data_hparams)

    text_data_batch = text_database()
    encoder = TransformerEncoder(vocab_size=text_database.source_vocab.vocab_size,
            hparams=extra_hparams)
    decoder = TransformerDecoder(vocab_size=text_database.target_vocab.vocab_size,
            hparams=extra_hparams)

    connector = ConstantConnector(output_size=decoder._hparams.embedding.dim)
    print('encoder decoder finished')
    src_text = text_data_batch['source_text_ids'][:, :extra_hparams['max_seq_length']]
    tgt_text = text_data_batch['target_text_ids'][:, :extra_hparams['max_seq_length']]

    src_text = tf.concat(
        [src_text, tf.zeros([tf.shape(src_text)[0],
            extra_hparams['max_seq_length']-tf.shape(src_text)[1]], dtype=tf.int64)], axis=1)

    tgt_text = tf.concat(
        [tgt_text, tf.zeros([tf.shape(tgt_text)[0],
            extra_hparams['max_seq_length']-tf.shape(tgt_text)[1]], dtype=tf.int64)], axis=1)

    # shifted right
    decoder_inputs = tf.concat((tf.ones_like(tgt_text[:, :1]), tgt_text[:, :-1]), -1)
    # 1 : BOS

    # print('src_text:{}'.format(src_text))
    encoder_output = encoder(src_text)
    # Decode
    # print('encoder_output:{}'.format(encoder_output.shape))
    logits, preds = decoder(decoder_inputs, encoder_output)

    labels = tgt_text
    istarget = tf.to_float(tf.not_equal(labels, 0))
    acc = tf.reduce_sum(tf.to_float(tf.equal(preds, tf.cast(labels, tf.int32)))*istarget)/ \
        tf.reduce_sum(istarget)

    tf.summary.scalar('acc', acc)

    mle_loss = mle_losses.average_sequence_sparse_softmax_cross_entropy(
        labels=labels,
        logits=logits,
        sequence_length=text_data_batch['target_length'])

    tf.summary.scalar('mean_loss', mle_loss)
    merged = tf.summary.merge_all()

    # Build train op. Only config the optimizer while using default settings
    # for other hyperparameters.
    opt_hparams={
        "optimizer": {
            "type": "MomentumOptimizer",
            "kwargs": {
                "learning_rate": 0.0001,
                "momentum": 0.9
            }
        }
    }
    train_op, global_step = opt.get_train_op(mle_loss, hparams=opt_hparams)

    ### Graph is done. Now start running
    saver = tf.train.Saver()
    # We shall wrap these environment setup codes
    with tf.Session() as sess:
        saver.restore(sess, tf.train.latest_checkpoint('model/'))
        print('restored!')
        mname = open('model/'+ '/checkpoint', 'r').read().split('"')[1]
        if not os.path.exists('results'): os.mkdir('results')
        with codecs.open('results/'+mname, 'w', 'utf-8') as fout:
            list_of_refs, hypotheses=[], []
            sess.run(tf.global_variables_initializer())
            sess.run(tf.local_variables_initializer())
            sess.run(tf.tables_initializer())
            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(sess=sess, coord=coord)

            try:
                while not coord.should_stop():
                    sources, targets, prds = sess.run(
                        [src_text, tgt_text, preds],
                        feed_dict={context.is_train():False})
                    for src,tgt,prd in zip(sources, targets, prds):
                        worddict = text_database._tgt_dataset
                        #TO DO(shr):evaluation metrics:bleu
                        # got = " ".join()
                        fout.write('src:{}\ntgt:{}\nprd:{}\n\n'.format(src,tgt,prd))
            except tf.errors.OutOfRangeError:
                print('Done -- epoch limit reached')
            finally:
                coord.request_stop()
            coord.join(threads)

