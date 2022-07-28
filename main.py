import logging
import argparse
import os
import random
import pandas as pd
import PySimpleGUI as sg
import platform
from datetime import timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument('-r', '--randomize', action='store_true', help='randomize modified time of local add-on '
                                                                            'folders')
argument_parser.add_argument('-l', '--log', type=str, help='set the logging level',
                             choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO')
args = argument_parser.parse_args()

# Randomize the last updated field of the local AddOn folders, for testing purposes
if args.randomize:
    max_time = datetime.now()
    min_time = (max_time + timedelta(days=-365))
    min_time, max_time = (int(min_time.timestamp()), int(max_time.timestamp()))
    for root, dirs, files in os.walk("./AddOns", topdown=False):
        for name in files + dirs:
            time = random.randrange(min_time, max_time)
            os.utime(os.path.join(root, name), (time, time))

log_level = getattr(logging, args.log, None)
if not isinstance(log_level, int):
    raise ValueError('Invalid log level: %s' % args.log)

logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s: %(message)s', datefmt='%m/%d/%Y %H:%M:%S')

CURSE_BASE_URL = "https://www.curseforge.com/wow/addons/"


def check_curseforge(urls, window):
    # For each addon, get the last modified time from CurseForge
    options = Options()
    options.headless = True
    options.add_argument("--window-size=1920,1200")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) /"
                         "Chrome/102.0.5005.63 Safari/537.36")
    options.add_argument('log-level=3')
    driver = webdriver.Chrome(options=options, service=Service(ChromeDriverManager().install()))
    result = []
    for count, url in enumerate(urls):
        result.append(get_last_updated(url, driver))
        # TODO: update progress bar with count
    return result
    # local_addons["Last Modified Source"] = [get_last_updated(url, driver) for url in local_addons['URL']]

def get_last_updated(url, driver):
    logging.info("Getting " + CURSE_BASE_URL + url)
    date = None
    try:
        driver.get(CURSE_BASE_URL + url)
        date = driver.find_element(By.TAG_NAME, 'abbr')
        date = date.get_attribute("data-epoch")
        date = datetime.fromtimestamp(int(date))
    except NoSuchElementException:
        logging.info("Couldn't find update time")
        pass
    except TimeoutException:
        logging.info("Connection timed out")
        pass
    else:
        logging.info("Updated on " + str(date))
    return date


# Get the information about known addons, namely which folders belong to which addon,
# and what is each addon's CurseForge url suffix
addons_info = pd.read_csv("./addon_folders.csv")

# Get the last modified time of each folder in the installed addon folder and store it in a DataFrame
#
# TODO: use the default installation folder of WoW
#   Check if it's a valid installation of WoW (.exe file exists, path to addons folder is correct)
#   If not, ask the user for the installation folder

addon_folder = Path("./AddOns")
folders = []
last_modified = []
for folder in addon_folder.iterdir():
    folders.append(folder.name)
    last_modified.append(datetime.fromtimestamp(folder.stat().st_mtime))

local_addons = pd.DataFrame(data={
    "Folder": folders,
    "Last Modified Local": last_modified
})

local_addons = local_addons.merge(addons_info, on="Folder")
# local_addons.to_excel("./Local addons.xlsx")     # for testing
pd.set_option('display.max_columns', None)
local_addons.set_index(["Name", "Folder"], inplace=True)
local_addons.sort_index()
latest_folder_index = local_addons.groupby("Name")['Last Modified Local'].transform(max) == \
                      local_addons["Last Modified Local"]
# Leave only the most recently modified folder for each addon, because that was the last time the addon was updated
local_addons = local_addons[latest_folder_index]
# Folder information is not needed anymore
local_addons = local_addons.droplevel('Folder')
local_addons = local_addons.reset_index()
# local_addons.to_excel("./Local addons filtered.xlsx")    # for testing

initial_screen = [sg.Button(button_text="Check for updates", key="check_button", visible=True)]
checking_screen = [sg.Column([[sg.Text("Checking add-on", key='checking_text', )]],
                             key='checking_screen', visible=False)]
# TODO: send local_addons['URL'] to check_curseforge

local_addons = local_addons[local_addons['Last Modified Local'] < local_addons["Last Modified Source"]]
# local_addons.to_excel("./Local addons that need update.xlsx")    # for testing

if __name__ == "__main__":

