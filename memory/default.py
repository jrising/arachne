from .long_term import LongTermMemory
from . import integration_long_term
from . import store_sqlalchemy, model_openai, index_whoosh
import chatwrap
import chatwrap.openaigpt

def get_store(sqlpath="sqlite:///memory/long_term.db"):
    return store_sqlalchemy.SQLAlchemyMemoryStore.from_url(sqlpath)

def create_long_term(sqlpath="sqlite:///memory/long_term.db", whooshpath="memory/whoosh", store=None):
    if store is None:
        store = get_store(sqlpath)
    model = model_openai.OpenAIMemoryModel(chatwrap.openaigpt)
    index = index_whoosh.WhooshMemoryIndex(whooshpath)
    return LongTermMemory(store, model, index)
