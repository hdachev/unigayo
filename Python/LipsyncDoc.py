# Papagayo, a lip-sync tool for use with Lost Marble's Moho
# Copyright (C) 2005 Mike Clifton
# Contact information at http://www.lostmarble.com
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os
import codecs
import ConfigParser
import wx
from phonemes import *
from utilities import *
from PronunciationDialog import PronunciationDialog
import SoundPlayer
import traceback
import sys
import breakdowns

strip_symbols = '.,!?;-/()'
strip_symbols += u'\N{INVERTED QUESTION MARK}'
strip_symbols += u'{POUND}12000'
strip_symbols += u''

###############################################################

class LipsyncPhoneme:
	def __init__(self):
		self.text = ""
		self.frame = 0

###############################################################

class LipsyncWord:
	def __init__(self):
		self.text = ""
		self.startFrame = 0
		self.endFrame = 0
		self.phonemes = []

	def RunBreakdown(self, parentWindow, language, languagemanager):
		self.phonemes = []
		try:
			text = self.text.strip(strip_symbols)
			details = languagemanager.language_table[language]
			if details["type"] == "breakdown":
				exec("import %s as breakdown" % details["breakdown_class"])
				pronunciation = breakdown.breakdownWord(text)
				for i in range(len(pronunciation)):
					try:
						pronunciation[i] = phoneme_conversion[pronunciation[i]]
					except:
						print "Unknown phoneme:", pronunciation[i], "in word:", text
			elif details["type"] == "dictionary":
				if languagemanager.current_language != language:
					languagemanager.LoadLanguage(details)
					languagemanager.current_language = language
				if details["case"] == "upper":
					pronunciation = languagemanager.phoneme_dictionary[text.upper()]
				elif details["case"] == "lower":
					pronunciation = languagemanager.phoneme_dictionary[text.lower()]
				else:
					pronunciation = languagemanager.phoneme_dictionary[text]					
			else:
				pronunciation = phonemeDictionary[text.upper()]
			for p in pronunciation:
				if len(p) == 0:
					continue
				phoneme = LipsyncPhoneme()
				phoneme.text = p
				self.phonemes.append(phoneme)
		except:
			traceback.print_exc()
			# this word was not found in the phoneme dictionary
			dlg = PronunciationDialog(parentWindow)
			dlg.wordLabel.SetLabel(dlg.wordLabel.GetLabel() + ' ' + self.text)
			if dlg.ShowModal() == wx.ID_OK:
				for p in dlg.phonemeCtrl.GetValue().split():
					if len(p) == 0:
						continue
					phoneme = LipsyncPhoneme()
					phoneme.text = p
					self.phonemes.append(phoneme)
			dlg.Destroy()

	def RepositionPhoneme(self, phoneme):
		id = 0
		for i in range(len(self.phonemes)):
			if phoneme is self.phonemes[i]:
				id = i
		if (id > 0) and (phoneme.frame < self.phonemes[id - 1].frame + 1):
			phoneme.frame = self.phonemes[id - 1].frame + 1
		if (id < len(self.phonemes) - 1) and (phoneme.frame > self.phonemes[id + 1].frame - 1):
			phoneme.frame = self.phonemes[id + 1].frame - 1
		if phoneme.frame < self.startFrame:
			phoneme.frame = self.startFrame
		if phoneme.frame > self.endFrame:
			phoneme.frame = self.endFrame

###############################################################

class LipsyncPhrase:
	def __init__(self):
		self.text = ""
		self.startFrame = 0
		self.endFrame = 0
		self.words = []

	def RunBreakdown(self, parentWindow, language, languagemanager):
		self.words = []
		for w in self.text.split():
			if len(w) == 0:
				continue
			word = LipsyncWord()
			word.text = w
			self.words.append(word)
		for word in self.words:
			word.RunBreakdown(parentWindow, language, languagemanager)

	def RepositionWord(self, word):
		id = 0
		for i in range(len(self.words)):
			if word is self.words[i]:
				id = i
		if (id > 0) and (word.startFrame < self.words[id - 1].endFrame + 1):
			word.startFrame = self.words[id - 1].endFrame + 1
			if word.endFrame < word.startFrame + 1:
				word.endFrame = word.startFrame + 1
		if (id < len(self.words) - 1) and (word.endFrame > self.words[id + 1].startFrame - 1):
			word.endFrame = self.words[id + 1].startFrame - 1
			if word.startFrame > word.endFrame - 1:
				word.startFrame = word.endFrame - 1
		if word.startFrame < self.startFrame:
			word.startFrame = self.startFrame
		if word.endFrame > self.endFrame:
			word.endFrame = self.endFrame
		if word.endFrame < word.startFrame:
			word.endFrame = word.startFrame
		frameDuration = word.endFrame - word.startFrame + 1
		phonemeCount = len(word.phonemes)
		# now divide up the total time by phonemes
		if frameDuration > 0 and phonemeCount > 0:
			framesPerPhoneme = float(frameDuration) / float(phonemeCount)
			if framesPerPhoneme < 1:
				framesPerPhoneme = 1
		else:
			framesPerPhoneme = 1
		# finally, assign frames based on phoneme durations
		curFrame = word.startFrame
		for phoneme in word.phonemes:
			phoneme.frame = int(round(curFrame))
			curFrame = curFrame + framesPerPhoneme
		for phoneme in word.phonemes:
			word.RepositionPhoneme(phoneme)

###############################################################

class LipsyncVoice:
	def __init__(self, doc, name = "Voice"):
		self.name = name
		self.text = ""
		self.phrases = []
		self.soundDuration = 72
		self.soundPath = "" #AB	
		self.sound = None
		self.doc = doc

	def RunBreakdown(self, parentWindow, language, languagemanager):
		frameDuration = self.soundDuration
		# make sure there is a space after all punctuation marks
		repeatLoop = True
		while repeatLoop:
			repeatLoop = False
			for i in range(len(self.text) - 1):
				if (self.text[i] in ".,!?;-/()") and (not self.text[i + 1].isspace()):
					self.text = self.text[:i + 1] + ' ' + self.text[i + 1:]
					repeatLoop = True
					break
		# break text into phrases
		self.phrases = []
		for line in self.text.splitlines():
			if len(line) == 0:
				continue
			phrase = LipsyncPhrase()
			phrase.text = line
			self.phrases.append(phrase)
		# now break down the phrases
		for phrase in self.phrases:
			phrase.RunBreakdown(parentWindow, language, languagemanager)
		# for first-guess frame alignment, count how many phonemes we have
		phonemeCount = 0
		for phrase in self.phrases:
			for word in phrase.words:
				if len(word.phonemes) == 0: # deal with unknown words
					phonemeCount = phonemeCount + 4
				for phoneme in word.phonemes:
					phonemeCount = phonemeCount + 1
		# now divide up the total time by phonemes
		if frameDuration > 0 and phonemeCount > 0:
			framesPerPhoneme = int(float(frameDuration) / float(phonemeCount))
			if framesPerPhoneme < 1:
				framesPerPhoneme = 1
		else:
			framesPerPhoneme = 1
		# finally, assign frames based on phoneme durations
		curFrame = 0
		for phrase in self.phrases:
			for word in phrase.words:
				for phoneme in word.phonemes:
					phoneme.frame = curFrame
					curFrame = curFrame + framesPerPhoneme
				if len(word.phonemes) == 0: # deal with unknown words
					word.startFrame = curFrame
					word.endFrame = curFrame + 3
					curFrame = curFrame + 4
				else:
					word.startFrame = word.phonemes[0].frame
					word.endFrame = word.phonemes[-1].frame + framesPerPhoneme - 1
			phrase.startFrame = phrase.words[0].startFrame
			phrase.endFrame = phrase.words[-1].endFrame

	def RepositionPhrase(self, phrase, lastFrame):
		id = 0
		for i in range(len(self.phrases)):
			if phrase is self.phrases[i]:
				id = i
		if (id > 0) and (phrase.startFrame < self.phrases[id - 1].endFrame + 1):
			phrase.startFrame = self.phrases[id - 1].endFrame + 1
			if phrase.endFrame < phrase.startFrame + 1:
				phrase.endFrame = phrase.startFrame + 1
		if (id < len(self.phrases) - 1) and (phrase.endFrame > self.phrases[id + 1].startFrame - 1):
			phrase.endFrame = self.phrases[id + 1].startFrame - 1
			if phrase.startFrame > phrase.endFrame - 1:
				phrase.startFrame = phrase.endFrame - 1
		if phrase.startFrame < 0:
			phrase.startFrame = 0
		if phrase.endFrame > lastFrame:
			phrase.endFrame = lastFrame
		if phrase.startFrame > phrase.endFrame - 1:
			phrase.startFrame = phrase.endFrame - 1
		# for first-guess frame alignment, count how many phonemes we have
		frameDuration = phrase.endFrame - phrase.startFrame + 1
		phonemeCount = 0
		for word in phrase.words:
			if len(word.phonemes) == 0: # deal with unknown words
				phonemeCount = phonemeCount + 4
			for phoneme in word.phonemes:
				phonemeCount = phonemeCount + 1
		# now divide up the total time by phonemes
		if frameDuration > 0 and phonemeCount > 0:
			framesPerPhoneme = float(frameDuration) / float(phonemeCount)
			if framesPerPhoneme < 1:
				framesPerPhoneme = 1
		else:
			framesPerPhoneme = 1
		# finally, assign frames based on phoneme durations
		curFrame = phrase.startFrame
		for word in phrase.words:
			for phoneme in word.phonemes:
				phoneme.frame = int(round(curFrame))
				curFrame = curFrame + framesPerPhoneme
			if len(word.phonemes) == 0: # deal with unknown words
				word.startFrame = curFrame
				word.endFrame = curFrame + 3
				curFrame = curFrame + 4
			else:
				word.startFrame = word.phonemes[0].frame
				word.endFrame = word.phonemes[-1].frame + int(round(framesPerPhoneme)) - 1
			phrase.RepositionWord(word)

	def Open(self, inFile, path):
		self.name = inFile.readline().strip()
		
		relativePath = inFile.readline().strip()
		if relativePath: 
			folderPath = os.path.split(path)[0]
			self.soundPath = os.path.abspath(os.path.join(folderPath, relativePath))
			self.OpenAudio(self.soundPath)
		
		tempText = inFile.readline().strip()
		self.text = tempText.replace('|','\n')
		
		numPhrases = int(inFile.readline())
		for p in range(numPhrases):
			phrase = LipsyncPhrase()
			phrase.text = inFile.readline().strip()
			phrase.startFrame = int(inFile.readline())
			phrase.endFrame = int(inFile.readline())
			numWords = int(inFile.readline())
			for w in range(numWords):
				word = LipsyncWord()
				wordLine = inFile.readline().split()
				word.text = wordLine[0]
				word.startFrame = int(wordLine[1])
				word.endFrame = int(wordLine[2])
				numPhonemes = int(wordLine[3])
				for p in range(numPhonemes):
					phoneme = LipsyncPhoneme()
					phonemeLine = inFile.readline().split()
					phoneme.frame = int(phonemeLine[0])
					phoneme.text = phonemeLine[1]
					word.phonemes.append(phoneme)
				phrase.words.append(word)
			self.phrases.append(phrase)
		#todo also open audio
		#here we need to combine path of doc with relative path of audio
		
	def OpenAudio(self, path):
		if self.sound is not None:
			del self.sound
			self.sound = None
		#self.soundPath = path.encode("utf-8")
		self.soundPath = path.encode('latin-1', 'replace')
		self.sound = SoundPlayer.SoundPlayer(self.soundPath)
		if self.sound.IsValid():
			self.soundDuration = int(self.sound.Duration() * self.doc.fps)
			if self.soundDuration < self.sound.Duration() * self.doc.fps:
				self.soundDuration += 1
		else:
			self.sound = None
			
	def Save(self, outFile, path): #need to write path to audio here
		outFile.write("\t%s\n" % self.name)
		
		if self.soundPath:
			folderPath = os.path.split(path)[0]
			relativePath = os.path.relpath(self.soundPath, folderPath)
			outFile.write("\t%s\n" % relativePath)
		else:
			outFile.write("\n")
		
		tempText = self.text.replace('\n','|')
		outFile.write("\t%s\n" % tempText)
		outFile.write("\t%d\n" % len(self.phrases))
		for phrase in self.phrases:
			outFile.write("\t\t%s\n" % phrase.text)
			outFile.write("\t\t%d\n" % phrase.startFrame)
			outFile.write("\t\t%d\n" % phrase.endFrame)
			outFile.write("\t\t%d\n" % len(phrase.words))
			for word in phrase.words:
				outFile.write("\t\t\t%s %d %d %d\n" % (word.text, word.startFrame, word.endFrame, len(word.phonemes)))
				for phoneme in word.phonemes:
					outFile.write("\t\t\t\t%d %s\n" % (phoneme.frame, phoneme.text))
		
			#todo save audio path as well
			
	def GetPhonemeAtFrame(self, frame):
		for phrase in self.phrases:
			if (frame <= phrase.endFrame) and (frame >= phrase.startFrame):
				# we found the phrase that contains this frame
				word = None
				for w in phrase.words:
					if (frame <= w.endFrame) and (frame >= w.startFrame):
						word = w # the frame is inside this word
						break
				if word is not None:
					# we found the word that contains this frame
					for i in range(len(word.phonemes) - 1, -1, -1):
						if frame >= word.phonemes[i].frame:
							return word.phonemes[i].text
				break
		return "rest"

	def Export(self, path):
		if len(self.phrases) > 0:
			startFrame = self.phrases[0].startFrame
			endFrame = self.phrases[-1].endFrame
		else:
			startFrame = 0
			endFrame = 1
		outFile = open(path, 'w')
		outFile.write("MohoSwitch1\n")
		phoneme = ""
		for frame in range(startFrame, endFrame + 1):
			nextPhoneme = self.GetPhonemeAtFrame(frame)
			if nextPhoneme != phoneme:
				if phoneme == "rest":
					# export an extra "rest" phoneme at the end of a pause between words or phrases
					outFile.write("%d %s\n" % (frame, phoneme))
				phoneme = nextPhoneme
				outFile.write("%d %s\n" % (frame + 1, phoneme))
		outFile.close()

	def ExportAlelo(self, path, language, languagemanager):
		outFile = open(path, 'w')
		for phrase in self.phrases:
			for word in phrase.words:
				text = word.text.strip(strip_symbols)
				details = languagemanager.language_table[language]
				if languagemanager.current_language != language:
					languagemanager.LoadLanguage(details)
					languagemanager.current_language = language
				if details["case"] == "upper":
					pronunciation = languagemanager.raw_dictionary[text.upper()]
				elif details["case"] == "lower":
					pronunciation = languagemanager.raw_dictionary[text.lower()]
				else:
					pronunciation = languagemanager.raw_dictionary[text]
				first = True
				position = -1
				for phoneme in word.phonemes:
					if first == True:
						first = False
					else:
						outFile.write("%s %d %d\n" % (lastPhoneme_text, lastPhoneme.frame, phoneme.frame-1))
					position += 1
					lastPhoneme_text = pronunciation[position]
					lastPhoneme = phoneme
				outFile.write("%s %d %d\n" % (lastPhoneme_text, lastPhoneme.frame, word.endFrame))
		outFile.close()

	def __del__(self):
		# Properly close down the sound object
		if self.sound is not None:
			del self.sound	
		
###############################################################

class LipsyncDoc:
	def __init__(self,langman,parent):
		self.dirty = False
		self.name = "Untitled"
		self.path = None
		self.fps = 24
		self.voices = []
		self.currentVoice = None
		self.language_manager = langman
		self.parent = parent

	def Open(self, path):
		self.dirty = False
		self.path = os.path.normpath(path)
		self.name = os.path.basename(path)
		#self.sound = None
		self.voices = []
		self.currentVoice = None
		inFile = codecs.open(self.path, 'r', 'latin-1', 'replace')
		inFile.readline() # discard the header
		#self.soundPath = inFile.readline().strip()
	#	if not os.path.isabs(self.soundPath):
	#		self.soundPath = os.path.normpath(os.path.dirname(self.path) + '/' + self.soundPath)
		self.fps = int(inFile.readline())
	#	self.soundDuration = int(inFile.readline())
		numVoices = int(inFile.readline())
		for i in range(numVoices):
			voice = LipsyncVoice(self)
			voice.Open(inFile, path)
			self.voices.append(voice)
		inFile.close()
		if len(self.voices) > 0:
			self.currentVoice = self.voices[0]

	def Save(self, path):
		self.path = os.path.normpath(path)
		self.name = os.path.basename(path)
		#if os.path.dirname(self.path) == os.path.dirname(self.soundPath):
		#	savedSoundPath = os.path.basename(self.soundPath)
		#else:
		#	savedSoundPath = self.soundPath
		outFile = codecs.open(self.path, 'w', 'latin-1', 'replace')
		outFile.write("lipsync version 1.1\n")
		#outFile.write("%s\n" % savedSoundPath)
		outFile.write("%d\n" % self.fps)
		#outFile.write("%d\n" % self.soundDuration)
		outFile.write("%d\n" % len(self.voices))
		for voice in self.voices:
			voice.Save(outFile, path)
		outFile.close()
		self.dirty = False

class LanguageManager:
	__shared_state = {}

	def __init__(self):
		self.__dict__ = self.__shared_state
		self.language_table = {}
		self.phoneme_dictionary = {}
		self.raw_dictionary = {}
		self.current_language = ""
		self.phoneme_set = []
		self.phoneme_conversion = {}
		self.InitLanguages()
		
	def LoadDictionary(self,path):
		try:
			inFile = open(path, 'r')
		except:
			print "Unable to open phoneme dictionary!:", path
			return
		# process dictioary entries
		for line in inFile.readlines():
			if line[0] == '#':
				continue # skip comments in the dictionary
			# strip out leading/trailing whitespace
			line.strip()
			line = line.rstrip('\r\n')
			
			# split into components
			entry = line.split()
			if len(entry) == 0:
				continue
			# check if this is a duplicate word (alternate transcriptions end with a number in parentheses) - if so, throw it out
			if entry[0].endswith(')'):
				continue
			# add this entry to the in-memory dictionary
			for i in range(len(entry)):
				if i == 0:
					self.phoneme_dictionary[entry[0]] = []
					self.raw_dictionary[entry[0]] = []
				else:
					rawentry = entry[i]
					try:
						entry[i] = self.phoneme_conversion[entry[i]]
					except:
						print "Unknown phoneme:", entry[i], "in word:", entry[0]
					self.phoneme_dictionary[entry[0]].append(entry[i])
					self.raw_dictionary[entry[0]].append(rawentry)
		inFile.close()
		inFile = None

	def LoadLanguage(self,language_config):
		if self.current_language == language_config["label"]:
			return
		self.current_language = language_config["label"]
		#PHONEME SET
		inFile = open(os.path.join(get_main_dir(),language_config["location"],language_config["phonemes"]), 'r')
		for line in inFile.readlines():
			if line[0] == '#':
				continue # skip comments in the dictionary
			# strip out leading/trailing whitespace
			line.strip()			
			line = line.rstrip('\r\n')
			self.phoneme_set.append(line)
		inFile.close()
		inFile = None
		#MAPPING TABLE
		if language_config["mappings"] != "none":
			inFile = open(os.path.join(get_main_dir(),language_config["location"],language_config["mappings"]), 'r')
			for line in inFile.readlines():
				if line[0] == '#':
					continue # skip comments in the dictionary
				# strip out leading/trailing whitespace
				line.strip()
				line = line.rstrip('\r\n')
				if len(line) == 0:
					continue
				entry = line.split(":")
				if len(entry) == 0:
					continue
				self.phoneme_conversion[entry[0]] = entry[1]
			inFile.close()
			inFile = None
		else:
			for phon in self.phoneme_set:
				self.phoneme_conversion[phon] = phon
			
		for dictionary in language_config["dictionaries"]:
			self.LoadDictionary(os.path.join(get_main_dir(),language_config["location"],language_config["dictionaries"][dictionary]))
		
	def LanguageDetails(self, dirname, names):
		if "language.ini" in names:			
			config = ConfigParser.ConfigParser()
			config.read(os.path.join(dirname,"language.ini"))
			label = config.get("configuration","label")
			ltype = config.get("configuration","type")
			details = {}
			details["label"] = label
			details["type"] = ltype
			details["location"] = dirname		
			if ltype == "breakdown":
				details["breakdown_class"] = config.get("configuration","breakdown_class")
				self.language_table[label] = details
			elif ltype == "dictionary":
				details["phonemes"] = config.get("configuration","phonemes")
				details["mappings"] = config.get("configuration","mappings")
				try:
					details["case"] = config.get("configuration","case")
				except:
					details["case"] = "upper"
				details["dictionaries"] = {}

				if config.has_section('dictionaries'):
					for key, value in config.items('dictionaries'):
						details["dictionaries"][key] = value
				self.language_table[label] = details
			else:
				print "unknown type ignored language not added to table"

	def InitLanguages(self):
		if len(self.language_table) > 0:
			return
		for path, dirs, files in os.walk(os.path.join(get_main_dir(), "rsrc/languages")):			
			if "language.ini" in files:
				self.LanguageDetails(path, files)
	
