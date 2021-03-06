# base imports
import os
import subprocess
import pandas as pd
import numpy as np
import datetime
import logging

# widget imports
from IPython.display import display
from ipywidgets import Layout, HBox
import ipywidgets as widgets
import ipysheet
import folium
import asyncio

# util imports
import kso_utils.db_utils as db_utils
import kso_utils.movie_utils as movie_utils
import kso_utils.spyfish_utils as spyfish_utils
import kso_utils.server_utils as server_utils
import kso_utils.tutorials_utils as t_utils
import kso_utils.koster_utils as koster_utils
import kso_utils.project_utils as project_utils

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
out_df = pd.DataFrame()

####################################################    
############### SITES FUNCTIONS ###################
####################################################
def map_site(db_info_dict: dict, project: project_utils.Project):
    """
    > This function takes a dictionary of database information and a project object as input, and
    returns a map of the sites in the database
    
    :param db_info_dict: a dictionary containing the information needed to connect to the database
    :type db_info_dict: dict
    :param project: The project object
    :return: A map with all the sites plotted on it.
    """
    if project.server == "SNIC":
      # Set initial location to Gothenburg 
      init_location = [57.708870, 11.974560]
    
    else:
      # Set initial location to Taranaki
      init_location = [-39.296109, 174.063916]

    # Create the initial kso map
    kso_map = folium.Map(location=init_location)

    # Read the csv file with site information
    sites_df = pd.read_csv(db_info_dict["local_sites_csv"])

    # Combine information of interest into a list to display for each site
    sites_df["site_info"] = sites_df.values.tolist()

    # Save the names of the columns
    df_cols = sites_df.columns

    # Add each site to the map 
    sites_df.apply(lambda row:folium.CircleMarker(location=[row[df_cols.str.contains("Latitude")], 
                                                            row[df_cols.str.contains("Longitude")]], 
                                                            radius = 14, popup=row["site_info"], 
                                                            tooltip=row[df_cols.str.contains("siteName", 
                                                            case=False)]).add_to(kso_map), axis=1)

    # Add a minimap to the corner for reference
    minimap = folium.plugins.MiniMap()
    kso_map = kso_map.add_child(minimap)
    
    # Return the map
    return kso_map


def open_sites_csv(db_initial_info: dict):
    """
    > This function loads the sites csv file into a pandas dataframe, and then loads the dataframe into
    an ipysheet
    
    :param db_initial_info: a dictionary with the following keys:
    :return: A dataframe with the sites information
    """
    # Load the csv with sites information
    sites_df = pd.read_csv(db_initial_info["local_sites_csv"])

    # Load the df as ipysheet
    sheet = ipysheet.from_dataframe(sites_df)

    return sheet
    
def display_changes(db_info_dict: dict, isheet: ipysheet.Sheet, local_csv: str):
    """
    It takes the dataframe from the ipysheet and compares it to the dataframe from the local csv file.
    If there are any differences, it highlights them and returns the dataframe with the changes
    highlighted
    
    :param db_info_dict: a dictionary containing the database information
    :type db_info_dict: dict
    :param isheet: The ipysheet object that contains the data
    :param local_csv: The name of the csv file that is stored locally
    :return: A tuple with the highlighted changes and the sheet_df
    """
    # Read the local csv file
    df = pd.read_csv(db_info_dict[local_csv])

    # Convert ipysheet to pandas
    sheet_df = ipysheet.to_dataframe(isheet)
    
    # Check the differences between the spreadsheet and sites_csv
    sheet_diff_df = pd.concat([df , sheet_df]).drop_duplicates(keep=False)
    
    # If changes in dataframes display them and ask the user to confirm them
    if sheet_diff_df.empty:
        logging.error("There are no changes to update")
        raise
    else:
        # Retieve the column name of the site_id
        site_id_col = [col for col in df.columns if 'site_id' in col][0]
        
        # Concatenate DataFrames and distinguish each frame with the keys parameter
        df_all = pd.concat([df.set_index(site_id_col), sheet_df.set_index(site_id_col)],
            axis='columns', keys=['Origin', 'Update'])
        
        # Rearrange columns to have them next to each other
        df_final = df_all.swaplevel(axis='columns')[df.columns[1:]]
        

        # Create a function to highlight the changes
        def highlight_diff(data, color='yellow'):
            attr = 'background-color: {}'.format(color)
            other = data.xs('Origin', axis='columns', level=-1)
            return pd.DataFrame(np.where(data.ne(other, level=0), attr, ''),
                                index=data.index, columns=data.columns)

        # Return the df with the changes highlighted
        highlight_changes = df_final.style.apply(highlight_diff, axis=None)

        return highlight_changes, sheet_df

def update_csv(db_info_dict: dict, project: project_utils.Project, sheet_df: pd.DataFrame, local_csv: str, serv_csv: str):
    """
    This function is used to update the csv files for the database
    
    :param db_info_dict: The dictionary containing the database information
    :param project: The project object
    :param sheet_df: The dataframe of the sheet you want to update
    :param local_csv: The name of the csv file in the local directory
    :param serv_csv: The name of the csv file in the server
    """
    # Create button to confirm changes
    confirm_button = widgets.Button(
      description = 'Yes, details are correct',
      layout=Layout(width='25%'),
      style = {'description_width': 'initial'},
      button_style='danger'
      )

    # Create button to deny changes
    deny_button = widgets.Button(
        description = 'No, I will go back and fix them',
        layout=Layout(width='45%'),
        style = {'description_width': 'initial'}, 
        button_style='danger'
    )

    # Save changes in survey csv locally and in the server
    async def f(sheet_df):
        x = await t_utils.wait_for_change(confirm_button,deny_button) #<---- Pass both buttons into the function
        if x == "Yes, details are correct": #<--- use if statement to trigger different events for the two buttons
            print("Checking if changes can be incorporated to the database")
            
            # Check if the project is the Spyfish Aotearoa
            if project.Project_name == "Spyfish_Aotearoa":
                # Rename columns to match schema fields
                sheet_df = spyfish_utils.process_spyfish_sites(sheet_df)
        
            # Select relevant fields
            sheet_df = sheet_df[
                ["site_id", "siteName", "decimalLatitude", "decimalLongitude", "geodeticDatum", "countryCode"]
            ]
    
            # Roadblock to prevent empty lat/long/datum/countrycode
            db_utils.test_table(
                sheet_df, "sites", sheet_df.columns
            )
            
            print("Updating the changes into the csv files for the database.")
            
            # Save the updated df locally
            sheet_df.to_csv(db_info_dict[local_csv],index=False)
        
            # Save the updated df in the server
            server_utils.update_csv_server(project, db_info_dict, orig_csv = serv_csv, updated_csv = local_csv)
            print("SUCCESS: The changes have been added!")
            
        else:
            print("Run this cell again when the changes are correct!")

    print("")
    print("")
    print("Are the site changes above correct?")
    display(HBox([confirm_button,deny_button])) #<----Display both buttons in an HBox
    asyncio.create_task(f(sheet_df))


####################################################    
############### MOVIES FUNCTIONS ###################
####################################################

def choose_movie_review():
    """
    This function creates a widget that allows the user to choose between two methods to review the
    movies.csv file.
    :return: The widget is being returned.
    """
    choose_movie_review_widget = widgets.RadioButtons(
          options=["Basic: Check for empty cells in the movies.csv","Advanced: Basic + Check format and metadata of each movie"],
          description='What method you want to use to review the movies:',
          disabled=False,
          layout=Layout(width='95%'),
          style = {'description_width': 'initial'}
      )
    display(choose_movie_review_widget)
    
    return choose_movie_review_widget

def check_movies_csv(db_initial_info: dict, project: project_utils.Project, review_method: widgets.Widget):
    """
    > The function `check_movies_csv` loads the csv with movies information and checks if it is empty
    
    :param db_initial_info: a dictionary with the following keys:
    :param project: The project name
    :param review_method: The method used to review the movies
    """
    # Load the csv with movies information
    movies_df = pd.read_csv(db_initial_info["local_movies_csv"])
    
    if review_method.value.startswith("Basic"):
      check_empty_movies_csv(db_initial_info, project, movies_df)


def check_empty_movies_csv(db_initial_info: dict, project: project_utils.Project, movies_df: pd.DataFrame):
    """
    It checks if the movies.csv is empty, if it is, it displays the movies.csv as an ipysheet and asks
    the user to fill it up
    
    :param db_initial_info: dict, project, movies_df: pd.DataFrame
    :type db_initial_info: dict
    :param project: the project object
    :param movies_df: the dataframe of the movies.csv file
    :type movies_df: pd.DataFrame
    """
    # Process Spyfish Aotearoa movies
    if project.Project_name == "Spyfish_Aotearoa":
        movies_df = spyfish_utils.process_spyfish_movies(movies_df)
        
    # Process KSO movies
    if project.Project_name == "Koster_Seafloor_Obs":
        movies_df = koster_utils.process_koster_movies_csv(movies_df)
    
    # Process template movies
    if project.Project_name == "Template project":
        # Add path of the movies
        movies_df["Fpath"] = "https://www.wildlife.ai/wp-content/uploads/2022/06/"+ movies_df["filename"]
    
    # Connect to database
    conn = db_utils.create_connection(db_initial_info['db_path'])
    
    # Reference movies with their respective sites
    sites_df = pd.read_sql_query("SELECT id, siteName FROM sites", conn)
    sites_df = sites_df.rename(columns={"id": "Site_id"})

    # Merge movies and sites dfs
    movies_df = pd.merge(
        movies_df, sites_df, how="left", on="siteName"
    )
    
    # Select only those fields of interest
    movies_db = movies_df[
        ["movie_id", "filename", "created_on", "fps", "duration", "sampling_start", "sampling_end", "Author", "Site_id", "Fpath"]
    ]

    # TODO if empty cells display the movies.csv
    # if ...:
        # Load the df as ipysheet
        # sheet = ipysheet.from_dataframe(movies_df)

        # print(There are empty cells, please fill them up and confirm the changes)
        # return sheet
        
    # Roadblock to prevent empty information
    db_utils.test_table(
        movies_db, "movies", movies_db.columns
    )
    
    # Check for sampling_start and sampling_end info
    movies_df = movie_utils.check_sampling_start_end(movies_df, db_initial_info)
    
    # Ensure date is ISO 8601:2004(E) and compatible with Darwin Data standards
    #date_time_check = pd.to_datetime(movies_df.created_on, infer_datetime_format=True)
#     print("The last dates from the created_on column are:")
#     print(date_time_check.tail())
   
    logging.info("movies.csv is all good!") 



def open_movies_csv(db_initial_info: dict):
    """
    It loads the movies csv file into a pandas dataframe, and then loads that dataframe into an ipysheet
    
    :param db_initial_info: a dictionary with the following keys:
    :return: A sheet with the movies information
    """
    # Load the csv with movies information
    movies_df = pd.read_csv(db_initial_info["local_movies_csv"])

    # Load the df as ipysheet
    sheet = ipysheet.from_dataframe(movies_df)

    return sheet


def check_movies_from_server(db_info_dict: dict, project: project_utils.Project):
    """
    It takes in a dataframe of movies and a dictionary of database information, and returns two
    dataframes: one of movies missing from the server, and one of movies missing from the csv
    
    :param db_info_dict: a dictionary with the following keys:
    :param project: the project object
    """
    # Load the csv with movies information
    movies_df = pd.read_csv(db_info_dict["local_movies_csv"]) 
    
    # Check if the project is the Spyfish Aotearoa
    if project.Project_name == "Spyfish_Aotearoa":
        # Retrieve movies that are missing info in the movies.csv
        missing_info = spyfish_utils.check_spyfish_movies(movies_df, db_info_dict)
        
    # Find out files missing from the Server
    missing_from_server = missing_info[missing_info["_merge"]=="left_only"]
    
    logging.info("There are", len(missing_from_server.index), "movies missing")
    
    # Find out files missing from the csv
    missing_from_csv = missing_info[missing_info["_merge"]=="right_only"].reset_index(drop=True)
            
    logging.info("There are", len(missing_from_csv.index), "movies missing from movies.csv. Their filenames are:")
#     print(*missing_from_csv.filename.unique(), sep = "\n")
    
    return missing_from_server, missing_from_csv

def select_deployment(missing_from_csv: pd.DataFrame):
    """
    > This function takes a dataframe of missing files and returns a widget that allows the user to
    select the deployment of interest
    
    :param missing_from_csv: a dataframe of the files that are missing from the csv file
    :return: A widget object
    """
    if missing_from_csv.shape[0]>0:        
        # Widget to select the deployment of interest
        deployment_widget = widgets.SelectMultiple(
            options = missing_from_csv.deployment_folder.unique(),
            description = 'New deployment:',
            disabled = False,
            layout=Layout(width='50%'),
            style = {'description_width': 'initial'}
        )
        display(deployment_widget)
        return deployment_widget
    
def select_eventdate():
    # Select the date 
    """
    > This function creates a date picker widget that allows the user to select a date. 
    
    The function is called `select_eventdate()` and it returns a date picker widget. 
    """
    date_widget = widgets.DatePicker(
        description='Date of deployment:',
        value = datetime.date.today(),
        disabled=False,
        layout=Layout(width='50%'),
        style = {'description_width': 'initial'}
    )
    display(date_widget)
    return date_widget


def update_new_deployments(deployment_selected: widgets.Widget, db_info_dict: dict, event_date: widgets.Widget):
    """
    It takes a deployment, downloads all the movies from that deployment, concatenates them, uploads the
    concatenated video to the S3 bucket, and deletes the raw movies from the S3 bucket
    
    :param deployment_selected: the deployment you want to concatenate
    :param db_info_dict: a dictionary with the following keys:
    :param event_date: the date of the event you want to concatenate
    """
    for deployment_i in deployment_selected.value:      
        logging.info(f"Starting to concatenate {deployment_i} out of {len(deployment_selected.value)} deployments selected")
        
        # Get a dataframe of movies from the deployment
        movies_s3_pd = server_utils.get_matching_s3_keys(db_info_dict["client"], 
                                                     db_info_dict["bucket"], 
                                                     prefix = deployment_i,
                                                     suffix = movie_utils.get_movie_extensions())
        
        # Create a list of the list of movies inside the deployment selected
        movie_files_server = movies_s3_pd.Key.unique().tolist()
        
        
        if len(movie_files_server)<2:
            logging.info(f"Deployment {deployment_i} will not be concatenated because it only has {movies_s3_pd.Key.unique()}")
        else:
            # Concatenate the files if multiple
            logging.info("The files", movie_files_server, "will be concatenated")

            # Start text file and list to keep track of the videos to concatenate
            textfile_name = "a_file.txt"
            textfile = open(textfile_name, "w")
            video_list = []           

            for movie_i in sorted(movie_files_server):
                # Specify the temporary output of the go pro file
                movie_i_output = movie_i.split("/")[-1]

                # Download the files from the S3 bucket
                if not os.path.exists(movie_i_output):
                    server_utils.download_object_from_s3(client = db_info_dict["client"],
                                                         bucket = db_info_dict["bucket"], 
                                                         key=movie_i,
                                                         filename=movie_i_output,
                                                        )
                # Keep track of the videos to concatenate 
                textfile.write("file '"+ movie_i_output + "'"+ "\n")
                video_list.append(movie_i_output)
            textfile.close()

      
            # Save eventdate as str
            EventDate_str = event_date.value.strftime("%d_%m_%Y")

            # Specify the name of the concatenated video
            filename = deployment_i.split("/")[-1]+"_"+EventDate_str+".MP4"

            # Concatenate the files
            if not os.path.exists(filename):
                logging.info("Concatenating ", filename)

                # Concatenate the videos
                subprocess.call(["ffmpeg", 
                                 "-f", "concat", 
                                 "-safe", "0",
                                 "-i", "a_file.txt", 
                                 "-c:a", "copy",
                                 "-c:v", "h264",
                                 "-crf", "22",
                                 filename])
                
            # Upload the concatenated video to the S3
            server_utils.upload_file_to_s3(
                db_info_dict["client"],
                bucket=db_info_dict["bucket"],
                key=deployment_i+"/"+filename,
                filename=filename,
            )

            logging.info(filename, "successfully uploaded to", deployment_i)

            # Delete the raw videos downloaded from the S3 bucket
            for f in video_list:
                os.remove(f)

            # Delete the text file
            os.remove(textfile_name)

            # Delete the concat video
            os.remove(filename)
            
            # Delete the movies from the S3 bucket
            for movie_i in sorted(movie_files_server):
                server_utils.delete_file_from_s3(client = db_info_dict["client"],
                                    bucket = db_info_dict["bucket"], 
                                    key=movie_i,
                                   )


        
        
# def upload_movies():
    
#     # Define widget to upload the files
#     mov_to_upload = widgets.FileUpload(
#         accept='.mpg',  # Accepted file extension e.g. '.txt', '.pdf', 'image/*', 'image/*,.pdf'
#         multiple=True  # True to accept multiple files upload else False
#     )
    
#     # Display the widget?
#     display(mov_to_upload)
    
#     main_out = widgets.Output()
#     display(main_out)
    
#     # TODO Copy the movie files to the movies folder
    
#     # Provide the site, location, date info of the movies
#     upload_info_movies()
#     print("uploaded")
    
# # Check that videos can be mapped
#     movies_df['exists'] = movies_df['Fpath'].map(os.path.isfile)    
    
# def upload_info_movies():

#     # Select the way to upload the info about the movies
#     widgets.ToggleButton(
#     value=False,
#     description=['I have a csv file with information about the movies',
#                  'I am happy to write here all the information about the movies'],
#     disabled=False,
#     button_style='success', # 'success', 'info', 'warning', 'danger' or ''
#     tooltip='Description',
#     icon='check'
# )
    
#     # Upload the information using a csv file
#     widgets.FileUpload(
#     accept='',  # Accepted file extension e.g. '.txt', '.pdf', 'image/*', 'image/*,.pdf'
#     multiple=False  # True to accept multiple files upload else False
# )
#     # Upload the information 
    
#     # the folder where the movies are
    
#     # Try to extract location and date from the movies 
#     widgets.DatePicker(
#     description='Pick a Date',
#     disabled=False
# )
    
#     # Run an interactive way to write metadata info about the movies
    
#     print("Thanks for providing all the required information about the movies")
    
    
    
    


# # Select multiple movies to include information of
# def go_pro_movies_to_update(df):
    
#     # Save the filenames of the movies missing
#     filename_missing_csv = df.location_and_filename.unique()
    
#     # Display the project options
#     movie_to_update = widgets.SelectMultiple(
#         options=filename_missing_csv,
#         rows=15,
#         layout=Layout(width='80%'),
#         description="GO pro movies:",
#         disabled=False,
        
#     )
    
#     display(movie_to_update)
#     return movie_to_update

# # Select one movie to include information of
# def full_movie_to_update(df):
    
#     # Save the filenames of the movies missing
#     filename_missing_csv = df.location_and_filename.unique()
    
#     # Display the project options
#     movie_to_update = widgets.Dropdown(
#         options=filename_missing_csv,
#         rows=15,
#         layout=Layout(width='80%'),
#         description="Full movie:",
#         disabled=False,
        
#     )
    
#     display(movie_to_update)
#     return movie_to_update


# # Select the info to add to the csv
# def info_to_csv(df, movies):
    
#     # Save the filenames of the movies missing
#     filename_missing_csv = df.location_and_filename.unique()
    
#     # Display the project options
#     movie_to_update = widgets.SelectMultiple(
#         options=filename_missing_csv,
#         rows=15,
#         layout=Layout(width='80%'),
#         description="Movie:",
#         disabled=False,
        
#     )
    
#     display(movie_to_update)
#     return movie_to_update
    
    