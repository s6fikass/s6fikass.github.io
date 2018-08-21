# Copyright 2015 Conchylicultor. All Rights Reserved.
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

"""
Loads the dialogue corpus, builds the vocabulary
"""

import numpy as np
import nltk  # For tokenize
import torch
from tqdm import tqdm  # Progress bar
import pickle  # Saving the data
import math  # For float comparison
import os  # Checking file existance
import random
import re
import string
import collections
from collections import defaultdict
from corpus.kvretdata import KvretData
import csv

class Batch:
    """Struct containing batches info
    """
    def __init__(self):
        self.encoderSeqs = []
        self.encoderSeqsLen = []
        self.decoderSeqs = []
        self.decoderSeqsLen = []
        self.kb_inputs = []
        self.kb_inputs_mask = []
        self.targetSeqs = []
        self.weights = []


class TextData:
    """Dataset class
    Warning: No vocabulary limit
    """

    availableCorpus = collections.OrderedDict([  # OrderedDict because the first element is the default choice
        ('kvret', KvretData),
    ])

    @staticmethod
    def corpusChoices():
        """Return the dataset availables
        Return:
            list<string>: the supported corpus
        """
        return list(TextData.availableCorpus.keys())

    def __init__(self,dataFile,validFile, testFile, useGlove = False):
        """Load all conversations
        Args:
            args: parameters of the model
        """
        # Model parameters
        self.vocabularySize = 0
        self.corpus = 'kvret'
        self.glove_fileName="data/glove_data/glove.840B.300d.txt"

        # Path variables
        self.corpusDir = os.path.join(dataFile)
        self.validcorpus = os.path.join(validFile)
        self.testcorpus = os.path.join(testFile)

        basePath = self._constructBasePath()
        self.fullSamplesPath = basePath +'.pkl'  # Full sentences length/vocab
        self.filteredSamplesPath = basePath + 'filtered.pkl'

        self.padToken = -1  # Padding
        self.goToken = -1  # Start of sequence
        self.eosToken = -1  # End of sequence
        self.eouToken= -1 # End of utterance
        self.unknownToken = -1  # Word dropped from vocabulary

        self.trainingSamples = []  # 2d array containing each question and his answer [[input,target,kb]]
        self.txtTrainingSamples = []
        self.txtValidationSamples = []
        self.validationSamples = []
        self.testSamples = []

        if useGlove:
            print("Loading Glove embedding from disks...")
            self.word_to_embedding_dict = self.load_embedding_from_disks(self.glove_fileName)
            print("Glove Embedding loaded from disks.")


        self.word2id = {}
        self.id2word = {}  # For a rapid conversion (Warning: If replace dict by list, modify the filtering to avoid linear complexity with del)
        self.idCount = {}  # Useful to filters the words (TODO: Could replace dict by list or use collections.Counter)

        self.loadCorpus()

        # Plot some stats:
        self._printStats()

        # if self.playDataset:
        #     self.playDataset()

    def _printStats(self):
        print('Loaded Kvret : {} words, {} QA'.format(len(self.word2id), len(self.trainingSamples)))

    def _constructBasePath(self):
        """Return the name of the base prefix of the current dataset
        """
        path = os.path.join('data' + os.sep + 'samples' + os.sep)
        path += 'dataset-{}'.format(self.corpus)

        return path

    def makeLighter(self, ratioDataset):
        """Only keep a small fraction of the dataset, given by the ratio
        """
        #if not math.isclose(ratioDataset, 1.0):
        #    self.shuffle()  # Really ?
        #    print('WARNING: Ratio feature not implemented !!!')
        pass

    def shuffle(self):
        """Shuffle the training samples
        """
        random.shuffle(self.trainingSamples)
        random.shuffle(self.validationSamples)
        random.shuffle(self.testSamples)

    # def _createBatch(self, samples):
    #     """Create a single batch from the list of sample. The batch size is automatically defined by the number of
    #     samples given.
    #     The inputs should already be inverted. The target should already have <go> and <eos>
    #     Warning: This function should not make direct calls to args.batchSize !!!
    #     Args:
    #         samples (list<Obj>): a list of samples, each sample being on the form [input, target]
    #     Return:
    #         Batch: a batch object en
    #     """
    #
    #     batch = Batch()
    #     batchSize = len(samples)
    #     self.maxLengthEnco = self.getInputMaxLength()
    #     self.maxLengthDeco = self.getTargetMaxLength()
    #
    #     # Create the batch tensor
    #     for i in range(batchSize):
    #         # Unpack the sample
    #         sample = samples[i]
    #         # TODO: Why re-processed that at each epoch ? Could precompute that
    #         print(sample[0])
    #
    #         batch.encoderSeqs.append(reversed(sample[0]))  # Reverse inputs (and not outputs), little trick as defined on the original seq2seq paper
    #         batch.decoderSeqs.append([self.goToken] + sample[1] + [self.eosToken])  # Add the <go> and <eos> tokens
    #         batch.targetSeqs.append(batch.decoderSeqs[-1][1:])  # Same as decoder, but shifted to the left (ignore the <go>)
    #
    #         # Long sentences should have been filtered during the dataset creation
    #
    #         assert len(batch.encoderSeqs[i]) <= self.maxLengthEnco
    #         assert len(batch.decoderSeqs[i]) <= self.maxLengthDeco +2
    #
    #         # TODO: Should use tf batch function to automatically add padding and batch samples
    #         # Add padding & define weight
    #         batch.encoderSeqs[i]   = [self.padToken] * (self.maxLengthEnco  - len(batch.encoderSeqs[i])) + batch.encoderSeqs[i]  # Left padding for the input
    #         batch.weights.append([1.0] * len(batch.targetSeqs[i]) + [0.0] * (self.maxLengthDeco - len(batch.targetSeqs[i])))
    #         batch.decoderSeqs[i] = batch.decoderSeqs[i] + [self.padToken] * (self.maxLengthDeco - len(batch.decoderSeqs[i]))
    #         batch.targetSeqs[i]  = batch.targetSeqs[i]  + [self.padToken] * (self.maxLengthDeco - len(batch.targetSeqs[i]))
    #
    #     # # Simple hack to reshape the batch
    #     # encoderSeqsT = []  # Corrected orientation
    #     # for i in range(self.maxLengthEnco):
    #     #     encoderSeqT = []
    #     #     for j in range(batchSize):
    #     #         encoderSeqT.append(batch.encoderSeqs[j][i])
    #     #     encoderSeqsT.append(encoderSeqT)
    #     # batch.encoderSeqs = encoderSeqsT
    #     #
    #     # decoderSeqsT = []
    #     # targetSeqsT = []
    #     # weightsT = []
    #     # for i in range(self.maxLengthDeco):
    #     #     decoderSeqT = []
    #     #     targetSeqT = []
    #     #     weightT = []
    #     #     for j in range(batchSize):
    #     #         decoderSeqT.append(batch.decoderSeqs[j][i])
    #     #         targetSeqT.append(batch.targetSeqs[j][i])
    #     #         weightT.append(batch.weights[j][i])
    #     #     decoderSeqsT.append(decoderSeqT)
    #     #     targetSeqsT.append(targetSeqT)
    #     #     weightsT.append(weightT)
    #     # batch.decoderSeqs = decoderSeqsT
    #     # batch.targetSeqs = targetSeqsT
    #     # batch.weights = weightsT
    #
    #     # # Debug
    #     #self.printBatch(batch)  # Input inverted, padding should be correct
    #     # print(self.sequence2str(samples[0][0]))
    #     # print(self.sequence2str(samples[0][1]))  # Check we did not modified the original sample
    #
    #     return batch

    def createMyBatch(self, samples, transpose=True):
        """
        Args:

        Return:
        """
        batch = Batch()
        batchSize = len(samples)
        self.maxLengthEnco = self.getInputMaxLength()
        self.maxLengthDeco = self.getTargetMaxLength()
        self.maxTriples = self.getMaxTriples()

        # for i in range(batchSize):
        #     print(samples[i][0])

        samples.sort(key=lambda x: len(x[0]), reverse=True)


        # Create the batch tensor
        for i in range(batchSize):
            # Unpack the sample
            sample = samples[i]
            batch.encoderSeqs.append(sample[0])  # Reverse inputs (and not outputs), little trick as defined on the original seq2seq paper
            batch.decoderSeqs.append([self.goToken] + sample[1] + [self.eosToken])  # Add the <go> and <eos> tokens
            batch.targetSeqs.append(batch.decoderSeqs[-1][1:])  # Same as decoder, but shifted to the left (ignore the <go>)
            batch.kb_inputs.append(sample[2])


            batch.encoderSeqsLen.append(len(sample[0]))
            batch.decoderSeqsLen.append(len(sample[1])+2)

            assert len(batch.encoderSeqs[i]) <= self.maxLengthEnco
            assert len(batch.decoderSeqs[i]) <= self.maxLengthDeco +2

            # TODO: Should use tf batch function to automatically add padding and batch samples
            # Add padding & define weight
            batch.encoderSeqs[i]   =   [self.padToken] * (self.maxLengthEnco  - len(batch.encoderSeqs[i])) +batch.encoderSeqs[i]   # Left padding for the input
            batch.weights.append([1.0] * len(batch.targetSeqs[i]) + [0.0] * (self.maxLengthDeco - len(batch.targetSeqs[i])))
            batch.decoderSeqs[i] = batch.decoderSeqs[i] + [self.padToken] * (self.maxLengthDeco - len(batch.decoderSeqs[i]))
            batch.targetSeqs[i]  = batch.targetSeqs[i]  + [self.padToken] * (self.maxLengthDeco - len(batch.targetSeqs[i]))

            batch.kb_inputs[i] = batch.kb_inputs[i] # + [0, 0, 0]* (self.maxTriples - len(batch.kb_inputs[i]))



        # print ("Before Reshaping %d" % len(batch.encoderSeqs))
        # print ("Before Reshaping %d" % len(batch.decoderSeqs))
        # Simple hack to reshape the batch
        if transpose:
            encoderSeqsT = []  # Corrected orientation
            for i in range(self.maxLengthEnco):
                encoderSeqT = []
                for j in range(batchSize):
                    encoderSeqT.append(batch.encoderSeqs[j][i])
                encoderSeqsT.append(encoderSeqT)
            batch.encoderSeqs = encoderSeqsT

            decoderSeqsT = []
            targetSeqsT = []
            weightsT = []
            for i in range(self.maxLengthDeco):
                decoderSeqT = []
                targetSeqT = []
                weightT = []
                for j in range(batchSize):
                    decoderSeqT.append(batch.decoderSeqs[j][i])
                    targetSeqT.append(batch.targetSeqs[j][i])
                    weightT.append(batch.weights[j][i])
                decoderSeqsT.append(decoderSeqT)
                targetSeqsT.append(targetSeqT)
                weightsT.append(weightT)
            batch.decoderSeqs = decoderSeqsT
            batch.targetSeqs = targetSeqsT
            batch.weights = weightsT
            # print ("After Reshaping %d" % len(batch.encoderSeqs))
            # print ("After Reshaping %d" % len(batch.decoderSeqs))

            # # Debug
            #self.printBatch(batch)  # Input inverted, padding should be correct
            #     print(self.sequence2str(samples[0][0]))
            #     print(self.sequence2str(samples[0][1]))  # Check we did not modified the original sample
        return batch

    def getBatches(self, batch_size=1,valid=False,test=False, transpose=True):
        """Prepare the batches for the current epoch
        Return:
            list<Batch>: Get a list of the batches for the next epoch
        """
        self.shuffle()
        self.batchSize=batch_size

        batches = []

        def genNextSamples():
            """ Generator over the mini-batch training samples
            """
            for i in range(0, self.getSampleSize(), self.batchSize):
                yield self.trainingSamples[i:min(i + self.batchSize, self.getSampleSize())]

        def genValidNextSamples():
            """ Generator over the mini-batch training samples
                """
            for i in range(0, len(self.validationSamples), self.batchSize):
                yield self.validationSamples[i:min(i + self.batchSize, len(self.validationSamples))]

        def genTestNextSamples():
            """ Generator over the mini-batch training samples
                """
            for i in range(0, len(self.testSamples), self.batchSize):
                yield self.testSamples[i:min(i + self.batchSize, len(self.testSamples))]

        # TODO: Should replace that by generator (better: by tf.queue)
        if valid:
            for samples in genValidNextSamples():
                batch = self.createMyBatch(samples, transpose)
                batches.append(batch)
        elif test:
            for samples in genTestNextSamples():
                batch = self.createMyBatch(samples, transpose)
                batches.append(batch)
        else:
            for samples in genNextSamples():
                batch = self.createMyBatch(samples, transpose)
                batches.append(batch)
        # remove
        #if len(batches[len(batches)-1].encoderSeqs)!=batches or len(batches[len(batches)-1].decoderSeqs) != batch_size :
        batches.pop()

        return batches

    def getSampleSize(self):
        """Return the size of the dataset
        Return:
            int: Number of training samples
        """
        return len(self.trainingSamples)

    def getVocabularySize(self):
        """Return the number of words present in the dataset
        Return:
            int: Number of word on the loader corpus
        """
        return len(self.word2id)

    def get_candidates(self, target_batches, all_predictions):
        candidate_sentences = []
        reference_sentences = []
        for target_batch, pridictions in zip(target_batches, all_predictions):
            for target, pridiction in zip(target_batch, pridictions):
                reference_sentences.append([self.sequence2str(target,clean=True)])
                candidate_sentences.append(self.sequence2str(pridiction,clean=True, tensor=True))
        return candidate_sentences, reference_sentences

    def loadCorpus(self):
        """Load/create the conversations data
        """
        datasetExist = os.path.isfile(self.filteredSamplesPath)
        if not datasetExist:  # First time we load the database: creating all files
            print('Training samples not found. Creating dataset...')

            datasetExist = os.path.isfile(self.fullSamplesPath)  # Try to construct the dataset from the preprocessed entry
            if not datasetExist:
                print('Constructing full dataset...')

                # Corpus creation
                corpusData = TextData.availableCorpus['kvret'](self.corpusDir)
                validData = TextData.availableCorpus['kvret'](self.validcorpus)
                testData = TextData.availableCorpus['kvret'](self.testcorpus)

                self.createFullCorpus(corpusData.getConversations())
                self.createFullCorpus(validData.getConversations(),valid=True)
                self.createFullCorpus(testData.getConversations(),test=True)

                self.saveDataset(self.fullSamplesPath)
            else:
                self.loadDataset(self.fullSamplesPath)
            self._printStats()

            print('Filtering words (vocabSize = {} )...'.format(
                self.getVocabularySize()
            ))
            self.filterFromFull()  # Extract the sub vocabulary for the given maxLength and filterVocab

            # Saving
            print('Saving dataset...')
            self.saveDataset(self.filteredSamplesPath)  # Saving tf samples
        else:
            self.loadDataset(self.filteredSamplesPath)


    def saveDataset(self, filename):
        """Save samples to file
        Args:
            filename (str): pickle filename
        """

        with open(os.path.join(filename), 'wb') as handle:
            data = {  # Warning: If adding something here, also modifying loadDataset
                'word2id': self.word2id,
                'id2word': self.id2word,
                'idCount': self.idCount,
                'trainingSamples': self.trainingSamples,
                'validationSamples': self.validationSamples,
                'testSamples': self.testSamples,
            }
            pickle.dump(data, handle, -1)  # Using the highest protocol available



            with open("data/samples/train.csv", "w") as output:

                writer = csv.writer(output, lineterminator='\n')
                writer.writerows(self.txtTrainingSamples)
            with open("data/samples/valid.csv", "w") as output:
                writer = csv.writer(output, lineterminator='\n')
                writer.writerows(self.txtValidationSamples)

    def loadDataset(self, filename):
        """Load samples from file
        Args:
            filename (str): pickle filename
        """
        dataset_path = os.path.join(filename)
        print('Loading dataset from {}'.format(dataset_path))
        with open(dataset_path, 'rb') as handle:
            data = pickle.load(handle)  # Warning: If adding something here, also modifying saveDataset
            self.word2id = data['word2id']
            self.id2word = data['id2word']
            self.idCount = data.get('idCount', None)
            self.trainingSamples = data['trainingSamples']
            self.validationSamples = data['validationSamples']
            self.testSamples = data['testSamples']

            self.padToken = self.word2id['<pad>']
            self.goToken = self.word2id['<go>']
            self.eouToken = self.word2id['<eou>']
            self.eosToken = self.word2id['<eos>']
            self.unknownToken = self.word2id['<unknown>']  # Restore special words

    def filterFromFull(self):
        """ Load the pre-processed full corpus and filter the vocabulary / sentences
        to match the given model options
        """

        def mergeSentences(sentences, fromEnd=False):
            """Merge the sentences until the max sentence length is reached
            Also decrement id count for unused sentences.
            Args:
                sentences (list<list<int>>): the list of sentences for the current line
                fromEnd (bool): Define the question on the answer
            Return:
                list<int>: the list of the word ids of the sentence
            """
            # We add sentence by sentence until we reach the maximum length
            merged = []

            # If question: we only keep the last sentences
            # If answer: we only keep the first sentences
            if fromEnd:
                sentences = reversed(sentences)

            for sentence in sentences:

                # If the total length is not too big, we still can add one more sentence
                if len(merged) + len(sentence) <= self.maxLength:
                    if fromEnd:  # Append the sentence
                        merged = sentence + merged
                    else:
                        merged = merged + sentence
                else:  # If the sentence is not used, neither are the words
                    for w in sentence:
                        self.idCount[w] -= 1
            return merged

        newSamples = []

        # 1st step: Iterate over all words and add filters the sentences
        # according to the sentence lengths
        for inputWords, targetWords, triples in tqdm(self.trainingSamples, desc='Filter sentences:', leave=False):
            # inputWords = mergeSentences(inputWords, fromEnd=True)
            # targetWords = mergeSentences(targetWords, fromEnd=False)

            newSamples.append([inputWords, targetWords, triples])
        words = []

        # WARNING: DO NOT FILTER THE UNKNOWN TOKEN !!! Only word which has count==0 ?

        # 2nd step: filter the unused words and replace them by the unknown token
        # This is also where we update the correnspondance dictionaries
        specialTokens = {  # TODO: bad HACK to filter the special tokens. Error prone if one day add new special tokens
            self.padToken,
            self.goToken,
            self.eouToken,
            self.eosToken,
            self.unknownToken
        }

        newMapping = {}  # Map the full words ids to the new one (TODO: Should be a list)
        newId = 0

        selectedWordIds = collections \
            .Counter(self.idCount) \
            .most_common(self.vocabularySize or None)  # Keep all if vocabularySize == 0
        selectedWordIds = {k for k, v in selectedWordIds } #if v > self.filterVocab}
        selectedWordIds |= specialTokens

        for wordId, count in [(i, self.idCount[i]) for i in range(len(self.idCount))]:  # Iterate in order
            if wordId in selectedWordIds:  # Update the word id
                newMapping[wordId] = newId
                word = self.id2word[wordId]  # The new id has changed, update the dictionaries
                del self.id2word[wordId]  # Will be recreated if newId == wordId
                self.word2id[word] = newId
                self.id2word[newId] = word
                newId += 1
            else:  # Cadidate to filtering, map it to unknownToken (Warning: don't filter special token)
                newMapping[wordId] = self.unknownToken
                del self.word2id[self.id2word[wordId]]  # The word isn't used anymore
                del self.id2word[wordId]

        # Last step: replace old ids by new ones and filters empty sentences
        def replace_words(words):
            valid = False  # Filter empty sequences
            for i, w in enumerate(words):
                words[i] = newMapping[w]
                if words[i] != self.unknownToken:  # Also filter if only contains unknown tokens
                    valid = True
            return valid

        # self.trainingSamples.clear()

        for inputWords, targetWords, triples in tqdm(newSamples, desc='Replace ids:', leave=False):
            valid = True
            valid &= replace_words(inputWords)
            valid &= replace_words(targetWords)
            valid &= targetWords.count(self.unknownToken) == 0  # Filter target with out-of-vocabulary target words ?

            if valid:
                self.trainingSamples.append([inputWords, targetWords, triples])  # TODO: Could replace list by tuple

        self.idCount.clear()  # Not usefull anymore. Free data

    def createFullCorpus(self, conversations,valid=False, test=False):
        """Extract all data from the given vocabulary.
        Save the data on disk. Note that the entire corpus is pre-processed
        without restriction on the sentence length or vocab size.
        """
        # Add standard tokens
        self.padToken = self.getWordId('<pad>')  # Padding (Warning: first things to add > id=0 !!)
        self.goToken = self.getWordId('<go>')  # Start of sequence
        self.eouToken = self.getWordId('<eou>')  # Start of sequence
        self.eosToken = self.getWordId('<eos>')  # End of sequence
        self.unknownToken = self.getWordId('<unknown>')  # Word dropped from vocabulary

        # Preprocessing data

        for conversation in tqdm(conversations, desc='Extract conversations'):
            self.extractConversation(conversation, valid, test)

        # The dataset will be saved in the same order it has been extracted

    def extractConversation(self, conversation, valid, test, herarical=False, truncate = False):
        """Extract the sample lines from the conversations
        Args:
            conversation (Obj): a conversation object containing the lines to extract
        """

        step = 2

        # Iterate over all the lines of the conversation
        input_conversation = []
        output_conversation = []
        input_txt_conversation = []
        output_txt_conversation = []
        triples = self.extractText(conversation['kb'], kb=True)
        for i in tqdm_wrap(
            range(0, len(conversation['lines']) - 1, step),  # We ignore the last line (no answer for it)
            desc='Conversation',
                leave=False):
            if herarical:

                if conversation['lines'][i]['turn'] == 'driver':
                    inputLine = conversation['lines'][i]
                    targetLine = conversation['lines'][i+1]
                    targetIntent= conversation['intent']
                    print(targetIntent)

                    input_conversation.extend(self.extractText(inputLine['utterance']))
                    output_conversation.extend(self.extractText(targetLine['utterance']))

                    if i < (len(conversation['lines'])-2):
                        input_conversation.append(self.eouToken)
                        output_conversation.append(self.eouToken)

            else:

                if conversation['lines'][i]['turn'] == 'driver':
                    targeState="Unknown"
                    inputLine = conversation['lines'][i]
                    targetLine = conversation['lines'][i+1]
                    targetIntent = conversation['intent']
                    if "slots" in targetLine:
                        targeState = targetLine["slots"]


                    if i >= 1:
                        input_conversation.append(self.eouToken)
                        input_conversation.extend(output_conversation)
                        input_conversation.append(self.eouToken)
                        # backup for text samples
                        input_txt_conversation.append("<eou>")
                        input_txt_conversation.append(output_txt_conversation)
                        input_txt_conversation.append("<eou>")

                    input_txt_conversation.append(inputLine['utterance'])
                    output_txt_conversation = targetLine['utterance']

                    input_conversation.extend(self.extractText(inputLine['utterance'], conversation['kb']))
                    output_conversation = self.extractText(targetLine['utterance'], conversation['kb'])



                if not valid and not test:  # Filter wrong samples (if one of the list is empty)
                    if truncate and ( len(input_conversation[:]) >= 40 or len(output_conversation[:]) >= 40) :
                    # truncate if too long
                        self.trainingSamples.append([input_conversation[len(input_conversation) - 40:], output_conversation[:40], triples])
                        self.txtTrainingSamples.append([input_txt_conversation[:], output_txt_conversation])
                    else:
                        self.trainingSamples.append([input_conversation[:], output_conversation[:], triples])
                        self.txtTrainingSamples.append([input_txt_conversation[:], output_txt_conversation])
                elif valid:
                    if truncate and (len(input_conversation[:]) >= 40 or len(output_conversation[:]) >= 40):
                        self.validationSamples.append([input_conversation[len(input_conversation) - 40:], output_conversation[:40], triples])
                    else:
                        self.validationSamples.append([input_conversation[:], output_conversation[:], triples])
                    self.txtValidationSamples.append([input_txt_conversation[:], output_txt_conversation])
                elif test:
                    self.testSamples.append([input_conversation[:], output_conversation[:], triples])

    def extractText(self, line, triples=[], kb = False):
        """Extract the words from a sample lines
        Args:
            line (str): a line containing the text to extract
        Return:
            list<list<int>>: the list of sentences of word ids of the sentence
        """
        if kb:
            triples = []
            for triple in line:
                entities=[]
                for entity in triple:
                    entities.append(self.getWordId(entity.lower()))
                triples.append(entities)
            return triples
        else:
            line = line.lower()
            count = 0
            entities ={}

            for ki in triples:
                if 'day' in ki[1].lower() and len(ki[2].lower().split(",")) > 1:
                    for kki in ki[2].lower().split(","):
                        if kki in re.findall(r"[\w']+|[^\s\w']", line):
                            if kki.strip() == ki[2].lower().split(",")[0]:
                                count = count + 1
                                if "raining" in line:
                                    print(line)
                                    line = re.sub(kki.strip(), "_entity_"+str(count)+"_", line)
                                    print(line)
                                entities["_entity_"+str(count)+"_"]=kki.strip()
                            if kki.strip() == ki[2].lower().split(",")[1]:
                                count = count + 1
                                line = re.sub(kki.strip(), "_entity_" + str(count) + "_", line)
                                entities["_entity_"+str(count)+"_"] = kki.strip()
                            if kki.strip() == ki[2].lower().split(",")[2]:
                                count = count + 1
                                line = re.sub(kki.strip(), "_entity_" + str(count) + "_", line)
                                entities["_entity_"+str(count)+"_"] = kki.strip()
                else:
                    if ki[2].lower() in line:
                        count = count + 1
                        line = re.sub(ki[2].strip(), "_entity_" + str(count) + "_", line)
                        entities["_entity_"+str(count)+"_"] = ki[2].strip()
                if ki[0].lower() in line:
                    count = count + 1
                    line = re.sub(ki[0].strip(), "_entity_" + str(count) + "_", line)
                    entities["_entity_"+str(count)+"_"] = ki[0].strip()


            sentences = []  # List[List[str]]
            # Extract sentences
            sentencesToken = re.findall(r"[\w']+|[^\s\w']", line.lower())

            # We add sentence by sentence until we reach the maximum length
            for i in range(len(sentencesToken)):
                if sentencesToken[i] in entities:
                    sentences.append(self.getWordId(entities[sentencesToken[i]]))
                else:
                    token = sentencesToken[i].strip(",").strip(".").strip(":").strip("?").\
                    strip("!").strip(";").strip(' \n\t').strip().strip(" ").strip('\t')
                    if len(token) == 0:
                        continue
                    sentences.append(self.getWordId(token))  # Create the vocabulary and the training sentences

            return sentences

    def load_embedding_from_disks(self, glove_filename, with_indexes=False):
        """
        Read a GloVe txt file. If `with_indexes=True`, we return a tuple of two dictionnaries
        `(word_to_index_dict, index_to_embedding_array)`, otherwise we return only a direct
        `word_to_embedding_dict` dictionnary mapping from a string to a numpy array.
        """
        if with_indexes:
            word_to_index_dict = dict()
            index_to_embedding_array = []
        else:
            word_to_embedding_dict = dict()

        with open(glove_filename, 'r') as glove_file:
            for (i, line) in enumerate(glove_file):

                split = line.split(' ')

                word = split[0]

                representation = split[1:]
                representation = np.array(
                    [float(val) for val in representation]
                )

                if with_indexes:
                    word_to_index_dict[word] = i
                    index_to_embedding_array.append(representation)
                else:
                    word_to_embedding_dict[word] = representation

        _WORD_NOT_FOUND = [0.0] * len(representation)  # Empty representation for unknown words.
        if with_indexes:
            _LAST_INDEX = i + 1
            word_to_index_dict = defaultdict(lambda: _LAST_INDEX, word_to_index_dict)
            index_to_embedding_array = np.array(index_to_embedding_array + [_WORD_NOT_FOUND])
            return word_to_index_dict, index_to_embedding_array
        else:
            word_to_embedding_dict = defaultdict(lambda: _WORD_NOT_FOUND, word_to_embedding_dict)
            return word_to_embedding_dict

    def getWordId(self, word, create=True):
        """Get the id of the word (and add it to the dictionary if not existing). If the word does not exist and
        create is set to False, the function will return the unknownToken value
        Args:
            word (str): word to add
            create (Bool): if True and the word does not exist already, the world will be added
        Return:
            int: the id of the word created
        """
        # Should we Keep only words with more than one occurrence ?

        word = word.lower()  # Ignore case

        # At inference, we simply look up for the word
        if not create:
            wordId = self.word2id.get(word, self.unknownToken)
        # Get the id if the word already exist
        elif word in self.word2id:
            wordId = self.word2id[word]
            self.idCount[wordId] += 1
        # If not, we create a new entry
        else:
            wordId = len(self.word2id)
            self.word2id[word] = wordId
            self.id2word[wordId] = word
            self.idCount[wordId] = 1

        return wordId

    def printBatch(self, batch):
        """Print a complete batch, useful for debugging
        Args:
            batch (Batch): a batch object
        """
        print('----- Print batch -----')
        for i in range(len(batch.encoderSeqs[0])):  # Batch size
            print('Encoder: {}'.format(self.batchSeq2str(batch.encoderSeqs, seqId=i)))
            print('Decoder: {}'.format(self.batchSeq2str(batch.decoderSeqs, seqId=i)))
            print('Targets: {}'.format(self.batchSeq2str(batch.targetSeqs, seqId=i)))
            print('Weights: {}'.format(' '.join([str(weight) for weight in [batchWeight[i] for batchWeight in batch.weights]])))

    def sequence2str(self, sequence, clean=False, reverse=False,tensor = False):
        """Convert a list of integer into a human readable string
        Args:
            sequence (list<int>): the sentence to print
            clean (Bool): if set, remove the <go>, <pad> and <eos> tokens
            reverse (Bool): for the input, option to restore the standard order
        Return:
            str: the sentence
        """
        try:
            if len(sequence) == 0:
                return ''
        except:
            print(sequence)
        if tensor:
            sequence=sequence.numpy()

        if not clean:
            return ' '.join([self.id2word[idx] for idx in sequence])

        sentence = []
        for wordId in sequence:
            if wordId == self.eosToken:  # End of generated sentence
                break
            elif wordId != self.padToken and wordId != self.goToken:
                sentence.append(self.id2word[wordId])

        if reverse:  # Reverse means input so no <eos> (otherwise pb with previous early stop)
            sentence.reverse()

        return self.detokenize(sentence)

    def sentence2sequence(self, sentence):
        list = sentence.split(' ')
        sequence=[]
        for token in list:
            sequence.append(self.word2id[token])
        return sequence

    def detokenize(self, tokens):
        """Slightly cleaner version of joining with spaces.
        Args:
            tokens (list<string>): the sentence to print
        Return:
            str: the sentence
        """
        return ''.join([
            ' ' + t if not t.startswith('\'') and
                       t not in string.punctuation
                    else t
            for t in tokens]).strip().capitalize()

    def batchSeq2str(self, batchSeq, seqId=0, **kwargs):
        """Convert a list of integer into a human readable string.
        The difference between the previous function is that on a batch object, the values have been reorganized as
        batch instead of sentence.
        Args:
            batchSeq (list<list<int>>): the sentence(s) to print
            seqId (int): the position of the sequence inside the batch
            kwargs: the formatting options( See sequence2str() )
        Return:
            str: the sentence
        """
        sequence = []
        for i in range(len(batchSeq)):  # Sequence length
            sequence.append(batchSeq[i][seqId])
        return self.sequence2str(sequence, **kwargs)

    def sentence2enco(self, sentence):
        """Encode a sequence and return a batch as an input for the model
        Return:
            Batch: a batch object containing the sentence, or none if something went wrong
        """

        if sentence == '':
            return None

        # First step: Divide the sentence in token
        tokens = nltk.word_tokenize(sentence)
        if len(tokens) > self.maxLength:
            return None

        # Second step: Convert the token in word ids
        wordIds = []
        for token in tokens:
            wordIds.append(self.getWordId(token, create=False))  # Create the vocabulary and the training sentences

        # Third step: creating the batch (add padding, reverse)
        batch = self._createBatch([[wordIds, []]])  # Mono batch, no target output

        return batch

    def deco2sentence(self, decoderOutputs):
        """Decode the output of the decoder and return a human friendly sentence
        decoderOutputs (list<np.array>):
        """
        sequence = []

        # Choose the words with the highest prediction score
        for out in decoderOutputs:
            sequence.append(np.argmax(out))  # Adding each predicted word ids

        return sequence  # We return the raw sentence. Let the caller do some cleaning eventually

    def playDataset(self):
        """Print a random dialogue from the dataset
        """
        print('Randomly play samples:')
        for i in range(self.playDataset):
            idSample = random.randint(0, len(self.trainingSamples) - 1)
            print('Q: {}'.format(self.sequence2str(self.trainingSamples[idSample][0], clean=True)))
            print('A: {}'.format(self.sequence2str(self.trainingSamples[idSample][1], clean=True)))
            print()
        pass

    def getInputMaxLength(self):
        return max(map(len, (s for [s, _,_] in self.trainingSamples)))

    def getTargetMaxLength(self):
        return max(map(len, (s for [_, s,_] in self.trainingSamples)))+2

    def getMaxTriples(self):
        return max(map(len, (s for [_, _,s] in self.trainingSamples)))

def tqdm_wrap(iterable, *args, **kwargs):
    """Forward an iterable eventually wrapped around a tqdm decorator
    The iterable is only wrapped if the iterable contains enough elements
    Args:
        iterable (list): An iterable object which define the __len__ method
        *args, **kwargs: the tqdm parameters
    Return:
        iter: The iterable eventually decorated
    """
    if len(iterable) > 100:
        return tqdm(iterable, *args, **kwargs)
    return iterable
