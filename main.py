import logging
import argparse
import os
import random
import pandas as pd
import PySimpleGUI as sg
import platform
import threading
import webbrowser
from datetime import timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException

CURSE_BASE_URL = "https://www.curseforge.com/wow/addons/"


def check_curseforge(urls, gui, result_ref):
    # For each addon, get the last modified time from CurseForge
    options = Options()
    options.headless = True
    options.add_argument("--window-size=1920,1200")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) /"
                         "Chrome/102.0.5005.63 Safari/537.36")
    options.add_argument('log-level=3')
    driver = webdriver.Chrome(options=options, service=Service(ChromeDriverManager().install()))
    for count, url in enumerate(urls):
        result_ref.append(get_last_updated(url, driver))
        gui.write_event_value(key='-PROGRESS-', value=count)
    gui.write_event_value('-THREAD-', '** DONE **')


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


if __name__ == "__main__":
    # print('name is __name__')
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('-r', '--randomize', action='store_true',
                                 help='randomize modified time of local add-on '
                                      'folders')
    argument_parser.add_argument('-l', '--log', type=str, help='set the logging level',
                                 choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO')
    args = argument_parser.parse_args()
    # print(args)

    log_level = getattr(logging, args.log, None)
    if not isinstance(log_level, int):
        raise ValueError('Invalid log level: %s' % args.log)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s: %(message)s', datefmt='%m/%d/%Y %H:%M:%S')

    # Randomize the last updated field of the local AddOn folders, for testing purposes
    if args.randomize:
        logging.debug('Randomizing addon folders')
        max_time = datetime.now()
        min_time = (max_time + timedelta(days=-365))
        min_time, max_time = (int(min_time.timestamp()), int(max_time.timestamp()))
        for root, dirs, files in os.walk("./AddOns", topdown=False):
            for name in files + dirs:
                time = random.randrange(min_time, max_time)
                os.utime(os.path.join(root, name), (time, time))
    else:
        logging.debug('Not randomizing')

    sg.theme('DarkAmber')

    logging.debug('Reading addons CSV')
    # Get the information about known addons, namely which folders belong to which addon,
    # and what is each addon's CurseForge url suffix
    addons_info = pd.read_csv("./addon_folders.csv")
    logging.debug('DataFrame shape: ' + str(addons_info.shape))

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

    layout = [[sg.Text("Checking add-ons", key='-TEXT-', visible=False)],
              [sg.ProgressBar(max_value=len(local_addons.index), orientation='h', key='-PROGRESS-', visible=False)],
              [sg.Table(values=[[]], key='-RESULT-', visible=False)],
              [sg.Button(button_text="Check for updates", key="-CHECK-", visible=True)],
              [sg.Button('Exit')]]
    logging.debug('Creating window')
    window = sg.Window(title='BlessForge', layout=layout, use_custom_titlebar=True)
    logging.debug(type(window))
    result = []

    #-----GUI event loop-----#
    logging.debug('Starting GUI loop')
    while True:
        logging.debug('GUI top of loop')
        event, values = window.read(timeout=300)
        logging.debug('Event: ' + str(event))
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        # Start checking CurseForge for updates
        elif event == '-CHECK-':
            result = []
            window['-CHECK-'].update(visible = False)
            window['-TEXT-'].update(visible = True)
            window['-PROGRESS-'].update(visible = True)
            threading.Thread(target=check_curseforge, args=(list(local_addons['URL']), window, result)).start()
        # Finished checking for updates, display results
        elif event == '-THREAD-':
            # Create a copy so that local addons still represent the status on disk
            addons_to_update = local_addons.copy()
            addons_to_update["Last Modified Source"] = result
            addons_to_update = addons_to_update[
                addons_to_update['Last Modified Local'] < addons_to_update["Last Modified Source"]]
            # addons_to_update.to_excel("./Local addons that need update.xlsx")    # for testing
            window['-CHECK-'].update(visible = True)
            window['-TEXT-'].update(visible = False)
            window['-PROGRESS-'].update(visible = False)
            table = [[sg.Text(name), sg.Text(text='Go to CurseForge', key=f'LINK {CURSE_BASE_URL + url}',
                                             )] for name, url in zip(addons_to_update['Name'], addons_to_update['URL'])]
            window['-RESULT-'].update(values=table)
        elif event.startswith('LINK '):
            url = event.split(' ')[1]
            webbrowser.open(url)

    # User closed the window
    window.close()
