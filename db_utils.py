# base imports
import os
import sqlite3
import logging
import db_starter.schema as schema
import pandas as pd

# util imports
import kso_utils.koster_utils as koster_utils
import kso_utils.spyfish_utils as spyfish_utils
import kso_utils.sgu_utils as sgu_utils

# Logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Utility functions for common database operations

# Initiate the database
def init_db(db_path: str):
    
    # Delete previous database versions if exists
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # Get sql command for db setup
    sql_setup = schema.sql
    # create a database connection
    conn = create_connection(r"{:s}".format(db_path))

    # create tables
    if conn is not None:
        # execute sql
        execute_sql(conn, sql_setup)
        return "Database creation success"
    else:
        return "Database creation failure"

def create_connection(db_file: str):
    """create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA foreign_keys = 1")
        return conn
    except sqlite3.Error as e:
        logging.error(e)

    return conn


def insert_many(conn: sqlite3.Connection, data: list, table: str, count: int):
    """
    Insert multiple rows into table
    :param conn: the Connection object
    :param data: data to be inserted into table
    :param table: table of interest
    :param count: number of fields
    :return:
    """

    values = (1,) * count
    values = str(values).replace("1", "?")

    cur = conn.cursor()
    cur.executemany(f"INSERT INTO {table} VALUES {values}", data)


def retrieve_query(conn: sqlite3.Connection, query: str):
    """
    Execute SQL query and returns output
    :param conn: the Connection object
    :param query: a SQL query
    :return:
    """
    try:
        cur = conn.cursor()
        cur.execute(query)
    except sqlite3.Error as e:
        logging.error(e)

    rows = cur.fetchall()

    return rows


def execute_sql(conn: sqlite3.Connection, sql: str):
    """Execute multiple SQL statements without return
    :param conn: Connection object
    :param sql: a string of SQL statements
    :return:
    """
    try:
        c = conn.cursor()
        c.executescript(sql)
    except sqlite3.Error as e:
        logging.error(e)


def add_to_table(db_path: str, table_name: str, values: list, num_fields: int):

    conn = create_connection(db_path)

    try:
        insert_many(
            conn,
            values,
            table_name,
            num_fields,
        )
    except sqlite3.Error as e:
        logging.error(e)

    conn.commit()

    logging.info(f"Updated {table_name}")


def test_table(df: pd.DataFrame, table_name: str, keys: list =["id"]):
    try:
        # check that there are no id columns with a NULL value, which means that they were not matched
        assert len(df[df[keys].isnull().any(axis=1)]) == 0
    except AssertionError:
        logging.error(
            f"The table {table_name} has invalid entries, please ensure that all columns are non-zero"
        )
        logging.error(
            f"The invalid entries are {df[df[keys].isnull().any(axis=1)]}"
        )


def get_id(row: int, field_name: str, table_name: str, conn: sqlite3.Connection, conditions: dict ={"a": "=b"}):

    # Get id from a table where a condition is met

    if isinstance(conditions, dict):
        condition_string = " AND ".join(
            [k + v[0] + f"{v[1:]}" for k, v in conditions.items()]
        )
    else:
        raise ValueError("Conditions should be specified as a dict, e.g. {'a', '=b'}")

    try:
        id_value = retrieve_query(
            conn, f"SELECT {field_name} FROM {table_name} WHERE {condition_string}"
        )[0][0]
    except IndexError:
        id_value = None
    return id_value


def find_duplicated_clips(conn: sqlite3.Connection):

    # Retrieve the information of all the clips uploaded
    subjects_df = pd.read_sql_query(
        "SELECT id, movie_id, clip_start_time, clip_end_time FROM subjects WHERE subject_type='clip'",
        conn,
    )

    # Find clips uploaded more than once
    duplicated_subjects_df = subjects_df[
        subjects_df.duplicated(
            ["movie_id", "clip_start_time", "clip_end_time"], keep=False
        )
    ]

    # Count how many time each clip has been uploaded
    times_uploaded_df = (
        duplicated_subjects_df.groupby(["movie_id", "clip_start_time"], as_index=False)
        .size()
        .to_frame("times")
    )

    return times_uploaded_df["times"].value_counts()

# ## Populate sites, movies and species

def add_sites(db_initial_info: dict, project_name: str, db_path: str):
    # Load the csv with sites information
    sites_df = pd.read_csv(db_initial_info["local_sites_csv"])
    
    # Check if the project is the Spyfish Aotearoa
    if project_name == "Spyfish_Aotearoa":
        # Rename columns to match schema fields
        sites_df = spyfish_utils.process_spyfish_sites(sites_df)
        
    # Select relevant fields
    sites_df = sites_df[
        ["site_id", "siteName", "decimalLatitude", "decimalLongitude", "geodeticDatum", "countryCode"]
    ]
    
    # Roadblock to prevent empty lat/long/datum/countrycode
    test_table(
        sites_df, "sites", sites_df.columns
    )

    # Add values to sites table
    add_to_table(
        db_path, "sites", [tuple(i) for i in sites_df.values], 6
    )


def add_movies(db_initial_info: dict, project_name: str, db_path: str):

    # Load the csv with movies information
    movies_df = pd.read_csv(db_initial_info["local_movies_csv"])
    
    # Check if the project is the Spyfish Aotearoa
    if project_name == "Spyfish_Aotearoa":
        movies_df = spyfish_utils.process_spyfish_movies(movies_df)
        
    # Check if the project is the KSO
    if project_name == "Koster_Seafloor_Obs":
        movies_df = koster_utils.process_koster_movies_csv(movies_df)
    
    # Connect to database
    conn = create_connection(db_path)
    
    # Reference movies with their respective sites
    sites_df = pd.read_sql_query("SELECT id, siteName FROM sites", conn)
    sites_df = sites_df.rename(columns={"id": "Site_id"})

    # Merge movies and sites dfs
    movies_df = pd.merge(
        movies_df, sites_df, how="left", on="siteName"
    )
    
    # Select only those fields of interest
    if "Fpath" not in movies_df.columns:
        movies_df["Fpath"] = movies_df["filename"]
        
    movies_db = movies_df[
        ["movie_id", "filename", "created_on", "fps", "duration",
         "sampling_start", "sampling_end", "Author", "Site_id", "Fpath"]
    ]

    # Roadblock to prevent empty information
    test_table(
        movies_db, "movies", movies_db.columns
    )
    
    # Add values to movies table
    add_to_table(
        db_path, "movies", [tuple(i) for i in movies_db.values], 10
    )

def add_photos(db_initial_info: dict, project_name: str, db_path: str):

    # Load the csv with photos information
    photos_df = pd.read_csv(db_initial_info["local_photos_csv"])
    
    
    # Check if the project is the KSO
    if project_name == "SGU":
        photos_df = sgu_utils.process_sgu_photos_csv(db_initial_info)
        
    # Select relevant fields
    photos_df = photos_df[
        ["ID", "filename", "created_on", "site_id", "fpath"]
    ]
    
    # Roadblock to prevent empty columns
    test_table(
        photos_df, "photos", photos_df.columns
    ) 

    # Add values to sites table
    add_to_table(
        db_path, "photos", [tuple(i) for i in photos_df.values], 5
    )


def add_species(db_initial_info: dict, project_name: str, db_path: str):

    # Load the csv with species information
    species_df = pd.read_csv(db_initial_info["local_species_csv"])
    
    # Select relevant fields
    species_df = species_df[
        ["species_id", "commonName", "scientificName", "taxonRank", "kingdom"]
    ]
    
    # Roadblock to prevent empty information
    test_table(
        species_df, "species", species_df.columns
    )
    
    # Add values to species table
    add_to_table(
        db_path, "species", [tuple(i) for i in species_df.values], 5
    )


