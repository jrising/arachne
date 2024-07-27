from abc import ABC, abstractmethod
from typing import List, Tuple

## For BayesianProvider
import spacy
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
import pickle
import pandas as pd

## For FeedCollector
import os, time
from datetime import datetime
import pytz
from sqlalchemy import create_engine, Table, Column, Integer, Float, String, MetaData, select, update, delete
from sqlalchemy.orm import sessionmaker

## For developing results
import numpy as np
from . import feedutils

# Define the Snippet data structure.
class Snippet:
    def __init__(self, link: str, offset: int, generator: str, snippet: str):
        self.link = link
        self.offset = offset
        self.generator = generator
        self.snippet = snippet

nlp = spacy.load('en_core_web_sm')

# Define MemoryProvider as an abstract base class.
class MemoryProvider(ABC):
    @abstractmethod
    def get_snippets(self, prompt: str) -> List[Tuple[float, Snippet]]:
        """
        Abstract method that takes a string prompt and returns a list of 
        Snippet objects each associated with a probability (0-1).
        """
        pass

    @abstractmethod
    def serialize(self, file_path: str) -> None:
        """
        Abstract method that serializes the object and writes it to the given file.
        """
        pass

    @classmethod
    @abstractmethod
    def deserialize(cls, file_path: str) -> 'MemoryProvider':
        """
        Class method that takes a serialized string and returns a deserialized 
        instance of the class.
        """
        pass

    @abstractmethod
    def learn(self, prompt: str, snippet: Snippet, value: float) -> None:
        """
        Abstract method that takes a string prompt, a Snippet object, and a 
        value (0-1).
        """
        pass

class BayesianProvider:
    def __init__(self):
        self.nlp = nlp
        self.count_vect = None
        self.clf = None
        self.vocab_set = set()
        self.count_filepath = None
        self.count_df = None
        self.pkl_filepath = None
        
    def process_text(self, text):
        return ' '.join(token.text.lower() for token in self.nlp(text) if not token.is_stop)
    
    def learn_document(self, doc, prob):
        """Update the model with a new document and its associated probability"""
        processed_doc = self.process_text(doc)
        
        # Update vocabulary
        self.update_counts(doc, np.random.choice([1, 2], p=[prob, 1 - prob]))
        for word in processed_doc.split():
            if word not in self.vocab_set:
                print("Ignoring " + word) # I don't have a way to add words yet, without messing up the encoding
                if os.path.exists(self.pkl_filepath):
                    os.unlink(self.pkl_filepath)
                
        # Update the classifier
        self.count_vect.vocabulary = {word: idx for idx, word in enumerate(sorted(self.vocab_set))}
        X = self.count_vect.transform([processed_doc])
        y = [prob]
        self.clf.partial_fit(X, y, classes=[0, 1])

    def evaluate_documents(self, documents):
        """Calculate probabilities for a list of documents"""
        processed_docs = [self.process_text(doc) for doc in documents]
        X_new_counts = self.count_vect.transform(processed_docs)
        probs = self.clf.predict_proba(X_new_counts)[:, 1]  # Probability of being interesting
        return probs
    
    # Function for deserialization
    def serialize(self, clean_only):
        self.count_df.to_csv(self.count_filepath, index=False)

        if not clean_only or os.path.exists(self.pkl_filepath):
            with open(self.pkl_filepath, 'wb') as f:
                pickle.dump((self.clf, self.count_vect, self.vocab_set, self.count_filepath), f)
            
    @classmethod
    def deserialize(cls, file_path):
        with open(file_path, 'rb') as f:
            clf, count_vect, vocab_set, count_filepath = pickle.load(f)
        instance = cls()
        instance.clf = clf
        instance.count_vect = count_vect
        instance.vocab_set = vocab_set
        instance.count_filepath = count_filepath
        instance.count_df = pd.read_csv(count_filepath)
        instance.pkl_filepath = file_path
        return instance
    
    @classmethod
    def create_from_csv(cls, file_path, pkl_file_path):
        instance = cls()
        df = pd.read_csv(file_path)
        df['token'] = df['token'].astype(str)
        instance.vocab_set = set(df.token)
        instance.clf = MultinomialNB()
        instance.count_vect = CountVectorizer()
        instance.count_vect.vocabulary = {word: idx for idx, word in enumerate(sorted(instance.vocab_set))}
        instance.count_filepath = file_path
        instance.count_df = df
        instance.pkl_filepath = pkl_file_path
        
        df_vocab = pd.DataFrame(sorted(instance.vocab_set), columns=['token'])
        df['count'] = df['count'].astype(int)
        for category_id in [1, 2]:
            subdf = df[df.bayes_categories_id == category_id]
            df_merged = pd.merge(df_vocab, subdf[['token','count']], on="token", how="left")
            df_merged['count'] = df_merged['count'].fillna(0)
            
            X = [df_merged['count']]
            y = [int(category_id == 1)]
            instance.clf.partial_fit(X, y, classes=[0, 1])

        instance.serialize(False) # save it now, and delete when it's dirty
            
        return instance

    def update_counts(self, doc, category):
        if self.count_df is None:
            return # skip it

        tokens = doc.split()
        token_counts = {}

        # Count occurrences of each token
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        
        # Update DataFrame with the token counts
        for token, count in token_counts.items():
            # Check if the token exists in the DataFrame for the given category
            token_exists = self.count_df[(self.count_df['token'] == token) & (self.count_df['bayes_categories_id'] == category)]
        
            if not token_exists.empty:
                # If the token exists, increment the count
                current_index = token_exists.index[0]
                self.count_df.at[current_index, 'count'] += count
            else:
                # If the token does not exist, create a new row with the initial count set to count
                new_id = self.count_df['id'].max() + 1 if not self.count_df.empty else 1
                new_row = pd.DataFrame({"id": [new_id], 
                                        "token": [token], 
                                        "bayes_categories_id": [category], 
                                        "count": [count]})
                self.count_df = pd.concat([self.count_df, new_row], ignore_index=True)
    
def get_bayesfeeds():
    if os.path.exists("memory/bayesfeeds.pkl"):
        return BayesianProvider.deserialize("memory/bayesfeeds.pkl")
    else:
        return BayesianProvider.create_from_csv("memory/tokencount.csv", "memory/bayesfeeds.pkl")
    
def get_engine_items():
    engine = create_engine('sqlite:///memory/feed_items.db')
    metadata = MetaData()

    items = Table('items', metadata,
                  Column('id', Integer, primary_key=True),
                  Column('feed', String),
                  Column('title', String),
                  Column('pubtime', String),
                  Column('link', String),
                  Column('description', String),
                  Column('uses', Float),
                  Column('lastused', Integer))
    
    if not os.path.isfile('memory/feed_items.db'):
        metadata.create_all(engine)
        
    return engine, items


def get_itemlist(engine, items):
    with engine.connect() as conn:
        # Select all entries from the 'items' table
        result = conn.execute(select(items))
        
        # Fetch all rows from the result
        rows = result.fetchall()
        columns = result.keys()
        
        # Process each entry
        for row in rows:
            yield dict(zip(columns, row))

def convert_datetime_to_short_description(date_str):
    local_dt = feedutils.parse_datetime(date_str)
    
    # Convert the datetime to local timezone
    local_tz = pytz.timezone('America/New_York')
    now = datetime.now(local_tz)
    
    # Check if the local datetime is the same date as the current local date
    if local_dt.date() == now.date():
        # Return the time in "HH:MM" format
        return local_dt.strftime('%H:%M')
    else:
        # Return the date in "Month Day" format
        return local_dt.strftime('%b %d')

def get_input_text(engine, items, count):
    bayesian_provider = get_bayesfeeds()

    itemlist = list(get_itemlist(engine, items))
    documents = [row['feed'] + ' ' + row['title'] + "\n" + row['description'] for row in itemlist]
    print(len(documents))

    # Evaluate new set of documents
    probs = bayesian_provider.evaluate_documents(documents)
    probs_after_uses = probs * np.array([max(0, 1 - row['uses']) for row in itemlist])
    
    chosen = np.random.choice(len(itemlist), size=count, replace=False, p=probs_after_uses / sum(probs_after_uses))

    ## Purge a collection of low-prob entries
    todelete = np.random.choice(len(itemlist), size=len(itemlist) // 100, replace=False, p=(1 - probs_after_uses) / sum(1 - probs_after_uses))
    no_delete_time = np.nonzero([(time.time() - row['lastused']) < 7 * 24 * 60 * 60 for row in itemlist])[0]
    no_delete = np.append(no_delete_time, chosen)
    todelete2 = [ii for ii in todelete if ii not in no_delete]
    delete_items(engine, items, [itemlist[ii]['id'] for ii in todelete2])

    texts = {itemlist[ii]['id']: f"Feed: {itemlist[ii]['feed']}\nLink: {itemlist[ii]['link']}\nPublished at: {convert_datetime_to_short_description(itemlist[ii]['pubtime'])}\nTitle: {itemlist[ii]['title']}\nDescription: {itemlist[ii]['description']}" for ii in chosen}
    incremenet_uses(engine, items, [itemlist[ii]['id'] for ii in chosen], 0.1)
    return texts

def incremenet_uses(engine, items, ids, inc):
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for id in ids:
            stmt = update(items).where(items.c.id == id).values(uses=items.c.uses + inc)
            session.execute(stmt)
        session.commit()

def delete_items(engine, items, ids):
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.execute(delete(items).where(items.c.id.in_(ids)))
        session.commit()
        
def vote_updown(id, prob):
    bayesian_provider = get_bayesfeeds()
    engine, items = get_engine_items()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        stmt = select(items).where(items.c.id == id)
        for record in session.execute(stmt).fetchall():
            print(record[1] + "\n" + record[4])
            bayesian_provider.learn_document(record[1] + "\n" + record[4], prob) # title and description
        # Don't delete after voting, because we might want to change our vote
        # conn.delete(record)
        # conn.commit()
    bayesian_provider.serialize(True)
