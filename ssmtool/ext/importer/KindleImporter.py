import mobi
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import os, re
from pathlib import Path
from difflib import SequenceMatcher
from sentence_splitter import split_text_into_sentences
from ssmtool.tools import addNotes
from ssmtool.dictionary import code, lookupin
import time



def get_section(bdata: bytes, loc_start, loc_end):
    start = max((loc_start-10)*150, 0)
    end = min((11+loc_end)*150, len(bdata))+1
    return bdata[start:end].decode('utf8', 'ignore')
def extract_sentence(s: str, word: str, lang: str):
    s = re.sub('<[^>]*>', ' ', s)
    s = re.sub('<.*$', ' ', s)
    s = re.sub('^.*>', ' ', s)
    word = re.sub('[\?\.!«»…,()\[\]]*', "", word)
    sents = split_text_into_sentences(s, lang)
    for sent in sents:
        if word in sent:
            return sent
    return None
def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()
def get_uniques(l: list):
    return list(set(l) - set([""]))


class KindleImporter(QDialog):
    def __init__(self, parent, fpath):
        super().__init__(parent)
        self.settings = parent.settings
        self.setWindowTitle("Import Kindle notes")
        self.parent = parent
        self.resize(700, 500)
        self.layout = QFormLayout(self)
        self.layout.addRow(QLabel("<strong>Select the correct book files for each title:</strong><br>"))
        with open(fpath, mode='r', encoding="utf-8-sig") as f:
            self.notes = f.read()
            self.notes = self.notes.replace(u"\ufeff","")
            self.notes = self.notes.splitlines()
        self.titles = self.get_titles()
        fpath_dir = os.path.dirname(fpath)
        bookpaths = list(Path(fpath_dir).rglob('*.mobi')) + list(Path(fpath_dir).rglob('*.azw'))
        self.bookfiles = self.get_names(bookpaths)
        self.renderBookOptions(self.bookfiles)
        self.layout.addRow(QLabel("<br><strong>Start importing</strong><br>"))
        self.find_context = QPushButton("Get context")
        self.find_context.clicked.connect(self.get_sents)
        self.layout.addRow(QLabel(str(len(self.notes[::5])) + " entries found in the file."), self.find_context)

    def get_titles(self):
        titles = get_uniques(self.notes[0::5])
        return titles
    def get_names(self, bookpaths):
        bookfiles = list(map(os.path.basename, bookpaths))
        return dict(zip(bookfiles, bookpaths))
    def renderBookOptions(self, bookfiles: dict):
        self.comboboxes = []
        for title in self.titles:
            self.comboboxes.append(QComboBox())
            self.comboboxes[-1].addItems(sorted(list(bookfiles.keys()), key=lambda x: similar(x, title), reverse=True))
            self.comboboxes[-1].addItem("<Ignore>")
            self.layout.addRow(QLabel(title), self.comboboxes[-1])
    def get_sents(self):
        self.find_context.setEnabled(False)
        locs = self.notes[1::5]
        titles = self.notes[0::5]
        self.highlights = self.notes[3::5]
        maxlen = min(len(self.highlights), len(locs))
        self.highlights = self.highlights[:maxlen]
        locs = locs[:maxlen]
        starts = list(map(lambda x: int(x.split("|")[0].split()[-1].split("-")[0]), locs))
        ends = list(map(lambda x: int(x.split("|")[0].split()[-1].split("-")[-1]), locs))
        book2file = {}
        for i in range(len(self.comboboxes)):
            if self.comboboxes[i].currentText() != "<Ignore>":
                book2file[self.titles[i]] = self.bookfiles[self.comboboxes[i].currentText()]
            else:
                book2file[self.titles[i]] = "<Ignore>"
        bdata = {}
        for bookname in book2file.keys():
            print(str(book2file[bookname]))
            if book2file[bookname] and book2file[bookname] != "<Ignore>":
                try:

                    tempdir, filepath = mobi.extract(str(book2file[bookname]))
                    with open(filepath, "rb") as f:
                        d = f.read()
                    bdata[bookname] = d
                except AttributeError:
                    bdata[bookname] = bytes("", encoding="utf8")
                    print(bookname, "failed to read")
                    continue
                except mobi.kindleunpack.unpackException as e:
                    bdata[bookname] = bytes("", encoding="utf8")
                    print(bookname, "failed to read", e)
                    continue
            else:
                bdata[bookname] = bytes("", encoding="utf8")
        self.sents_count_label = QLabel("0 sentences found")
        self.lookup_button = QPushButton("Look up")
        self.lookup_button.setEnabled(False)
        self.lookup_button.clicked.connect(self.define_words)
        self.layout.addRow(self.sents_count_label, self.lookup_button)
        count = 0
        self.sents = []

        for i in range(maxlen):
            sec = get_section(bdata[titles[i]], starts[i], ends[i])
            sent = extract_sentence(sec, self.highlights[i], code[self.parent.settings.value("target_language")])
            if sent:
                count += 1
                self.sents_count_label.setText(str(count) + " sentences found")
                QApplication.processEvents()
            self.sents.append(sent)
        self.lookup_button.setEnabled(True)
    
    def define_words(self):
        self.lookup_button.setEnabled(False)
        self.words = []
        self.definitions = []
        self.definition2s = []
        self.definition_count_label = QLabel("0 definitions found")
        self.anki_button = QPushButton("Add notes to Anki")
        self.anki_button.setEnabled(False)
        self.anki_button.clicked.connect(self.to_anki)
        self.layout.addRow(self.definition_count_label, self.anki_button)

        count = 0
        for i in range(len(self.highlights)):
            word = self.highlights[i]
            if self.sents[i]:
                item = self.parent.lookup(word, record=False)
                if not item['definition'].startswith("<b>Definition for"):
                    count += 1
                    self.words.append(item['word'])
                    self.definitions.append(item['definition'])
                    self.definition_count_label.setText(str(count) + " definitions found")
                    QApplication.processEvents()
                else:
                    self.words.append(word)
                    self.definitions.append("")
                self.definition2s.append(item.get('definition2', ""))
            else: 
                self.definitions.append("")
                self.words.append("")
                self.definition2s.append("")
        
        self.anki_button.setEnabled(True)

    
    def to_anki(self):
        notes = []
        for word, sentence, definition, definition2 in zip(self.words, self.sents, self.definitions, self.definition2s):
            if word and sentence and definition:
                tags = self.parent.settings.value("tags", "ssmtool").strip() + " kindle"
                content = {
                    "deckName": self.parent.settings.value("deck_name"),
                    "modelName": self.parent.settings.value("note_type"),
                    "fields": {
                        self.parent.settings.value("sentence_field"): sentence,
                        self.parent.settings.value("word_field"): word,
                    },
                    "tags": tags.split(" ")
                }
                definition = definition.replace("\n", "<br>")
                content['fields'][self.parent.settings.value('definition_field')] = definition
                if self.settings.value("dict_source2", "Disabled") != 'Disabled':
                    try:
                        definition2 = definition2.replace("\n", "<br>")
                        content['fields'][self.parent.settings.value('definition2_field')] = definition2
                    except Exception as e:
                        return
                notes.append(content)
        res = addNotes(self.parent.settings.value("anki_api"), notes)
        self.layout.addRow(QLabel(str(len(notes)) + " notes have been exported, of which " + str(len([i for i in res if i]))+ " were successfully added to your collection."))
        


        
