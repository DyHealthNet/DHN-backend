import json
import os
import timeit
# we were using the sqlalchemy library to connect to the database, but you should probably change it to
# the django ORM
from sqlalchemy import select, func, text
from sqlalchemy.engine import URL, create_engine
from sqlalchemy.orm import sessionmaker


url = url_object = URL.create(
    "postgresql",
    username="postgres",
    password="password",  # plain (unescaped) text
    host="0.0.0.0",
    port=9852,
    database="postgres",
)
engine = create_engine(url)

def query_low_body(session):
    query = """
    SELECT *
    FROM view_description_fts
    WHERE to_tsvector('english', description) @@ plainto_tsquery('english', 'low body');
    """
    result = session.execute(text(query)).fetchall()
    return result

def query_brca(session):
    query = """
    SELECT *
    FROM view_description_fts
    WHERE display_name ILIKE 'brca%';
    """
    result = session.execute(text(query)).fetchall()
    return result

if __name__ == "__main__":
    Session = sessionmaker(bind=engine)
    session = Session()

    low_body_results = query_low_body(session)
    print("Results for 'low body':")
    for row in low_body_results:
        print(row)

    brca_results = query_brca(session)
    print("Results for 'brca':")
    for row in brca_results:
        print(row)

    # Schließen Sie die Session
    session.close()