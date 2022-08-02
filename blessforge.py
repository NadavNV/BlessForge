import logging
import argparse
import os
import random
import pandas as pd
import PySimpleGUI as sg
import platform
import threading
import webbrowser
from os import path
from datetime import timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

CURSE_BASE_URL = "https://www.curseforge.com/wow/addons/"
LINK_FONT = ('Courier New', 11, 'underline italic')
DEFAULT_FONT = ('Courier New', 11, 'normal')
TIME_TO_WAIT = 30
ERROR_MESSAGE = 'Error, try again'


def check_curseforge(urls, gui, result_ref, start_closing):
    # For each addon, get the last modified time from CurseForge
    options = Options()
    options.headless = True
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) /"
                         "Chrome/102.0.5005.63 Safari/537.36")
    options.add_argument('log-level=3')
    gui.write_event_value(key='-PROGRESS-', value=f'0 of {len(urls)}')
    with webdriver.Chrome(options=options, service=Service(ChromeDriverManager().install())) as driver:
        driver.set_page_load_timeout(TIME_TO_WAIT)
        for count, url in enumerate(urls):
            if start_closing.is_set():
                break
            gui.write_event_value(key='-PROGRESS-', value=f'{count + 1} of {len(urls)}')
            try:
                result_ref.append(get_last_updated(url, driver))
            except WebDriverException:
                result_ref.append(None)
                continue
    gui.write_event_value('-THREAD-', '** DONE **')


def get_last_updated(url, driver):
    logging.info("Getting " + CURSE_BASE_URL + url)
    try:
        driver.get(CURSE_BASE_URL + url)
        date = driver.find_element(By.TAG_NAME, 'abbr')
        date = date.get_attribute("data-epoch")
        date = datetime.fromtimestamp(int(date))
    except NoSuchElementException:
        logging.info("Couldn't find update time")
        return None
    except TimeoutException:
        logging.info("Connection timed out")
        return None
    else:
        logging.info("Updated on " + str(date))
        return date


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('-r', '--randomize', action='store_true',
                                 help='randomize modified time of local add-on '
                                      'folders')
    argument_parser.add_argument('-l', '--log', type=str.upper, help='set the logging level',
                                 choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO')
    args = argument_parser.parse_args()

    log_level = getattr(logging, args.log, None)
    if not isinstance(log_level, int):
        raise ValueError('Invalid log level: %s' % args.log)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s: %(message)s', datefmt='%m/%d/%Y %H:%M:%S')

    install_folder = ''

    if not path.exists("./local.info"):
        match platform.system():
            case 'Windows':
                install_folder = 'C:/Program Files/World of Warcraft/'
            case 'Darwin':  # Mac
                install_folder = 'Macintosh HD/Applications/World of Warcraft'
            case _:
                sg.popup('World of Warcraft is not supported on this platform!')

        if install_folder == '':
            exit()

        install_folder = Path(install_folder.join('_retail_/Interface/AddOns'))
        while not path.exists(install_folder):
            install_folder = sg.popup_get_folder("Could not find AddOns, please select the AddOns folder",
                                                 title="BlessForge")
            logging.debug('Install folder: ' + str(install_folder))
            if install_folder is None:
                exit()
        with open("local.info", mode='xt') as file:
            file.write(str(install_folder))
    else:
        with open("local.info") as file:
            install_folder = file.readline()

    logging.debug('Reading addons CSV')
    # Get the information about known addons, namely which folders belong to which addon,
    # and what is each addon's CurseForge url suffix
    addons_info = pd.read_csv("./addon_folders.csv")
    logging.debug('DataFrame shape: ' + str(addons_info.shape))

    install_folder = Path(install_folder)

    # Randomize the last updated field of the local AddOn folders, for testing purposes
    if args.randomize:
        logging.debug('Randomizing addon folders')
        max_time = datetime.now()
        min_time = (max_time + timedelta(days=-365))
        min_time, max_time = (int(min_time.timestamp()), int(max_time.timestamp()))
        for root, dirs, files in os.walk(install_folder, topdown=False):
            for name in files + dirs:
                time = random.randrange(min_time, max_time)
                os.utime(os.path.join(root, name), (time, time))
    else:
        logging.debug('Not randomizing')

    folders = []
    last_modified = []
    for folder in install_folder.iterdir():
        folders.append(folder.name)
        last_modified.append(datetime.fromtimestamp(folder.stat().st_mtime))

    local_addons = pd.DataFrame(data={
        "Folder": folders,
        "Last Modified Local": last_modified
    })

    local_addons = local_addons.merge(addons_info, on="Folder")
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

    main_layout = [[sg.Text("Checking add-ons...", key='-TEXT-', visible=False, size=30, justification='center')],
                   [sg.Text(key='-PROGRESS-', visible=False, size=30, justification='center')],
                   [sg.Button(button_text="Check for updates (May take a while)", key="-CHECK-", visible=True)],
                   [sg.Button('Exit')]]
    logging.debug('Creating main window')
    main_window = sg.Window(title='BlessForge', layout=main_layout, font=DEFAULT_FONT,
                            enable_close_attempted_event=True, element_justification='center')
    main_window.finalize()
    main_window.write_event_value(key='-CHECK-', value='')
    last_modified_source = []

    # -----GUI event loop-----#
    start_closing = threading.Event()
    scraping_thread = None
    logging.debug('Starting GUI loop')
    while True:
        window, event, values = sg.read_all_windows(timeout=300)
        if event != '__TIMEOUT__':
            logging.debug('Window: ' + str(window))
            logging.debug('Event: ' + str(event))
            logging.debug('Values: ' + str(values))
        if event in (sg.WIN_CLOSED, sg.WIN_CLOSE_ATTEMPTED_EVENT, 'Exit'):
            if window == main_window:
                if scraping_thread is None or not scraping_thread.is_alive():
                    break
                else:
                    start_closing.set()
                    main_window['-TEXT-'].update('Finishing up...')
                    main_window['-PROGRESS-'].update(visible=False)
            else:
                window.close()
        # Start checking CurseForge for updates
        elif event == '-CHECK-':
            last_modified_source = []
            main_window['-CHECK-'].update(visible=False)
            main_window['-TEXT-'].update(visible=True)
            main_window['-PROGRESS-'].update(visible=True)
            scraping_thread = threading.Thread(target=check_curseforge, args=(list(local_addons['URL']), main_window,
                                                                              last_modified_source, start_closing))
            scraping_thread.start()

        # Finished checking for updates, display results
        elif event == '-THREAD-':
            if start_closing.is_set():  # No need to create a result if user is trying to close the app
                break
            else:
                # Create a copy so that local addons still represent the status on disk
                addons_to_update = local_addons.copy()
                addons_to_update["Last Modified Source"] = last_modified_source
                missing_data = addons_to_update[addons_to_update.isnull().any(axis=1)].index.to_series()
                addons_to_update.loc[missing_data, "Last Modified Source"] = datetime.now()
                addons_to_update.loc[missing_data, "URL"] = ERROR_MESSAGE
                addons_to_update = addons_to_update[
                    addons_to_update['Last Modified Local'] < addons_to_update["Last Modified Source"]]
                main_window['-CHECK-'].update(visible=True)
                main_window['-TEXT-'].update(visible=False)
                main_window['-PROGRESS-'].update(visible=False)
                addons_to_update_table = []
                for name, url in zip(addons_to_update['Name'], addons_to_update['URL']):
                    if url == ERROR_MESSAGE:
                        addons_to_update_table.append([sg.Text(name, size=len(max(addons_to_update['Name'], key=len))),
                                                       sg.Text(ERROR_MESSAGE)])
                    else:
                        addons_to_update_table.append([sg.Text(name, size=len(max(addons_to_update['Name'], key=len))),
                                                       sg.Text('Go to CurseForge', key=f'LINK {CURSE_BASE_URL+url}',
                                                               enable_events=True, font=LINK_FONT)])
                sg.Window(title='Outdated AddOns', layout=[[sg.Column(layout=addons_to_update_table, scrollable=True,
                                                                      vertical_scroll_only=True)]],
                          finalize=True, enable_close_attempted_event=True)
        elif event.startswith('LINK '):
            url = event.split(' ')[1]
            webbrowser.open(url, new=2)
        elif event == '-PROGRESS-':
            main_window['-PROGRESS-'].update(value=values['-PROGRESS-'])
            pass

    # User closed the window
    main_window.close()


if __name__ == "__main__":
    main()
