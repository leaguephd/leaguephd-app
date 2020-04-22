import asyncio
import argparse
import json
import logging
import requests
import sys
from asyncqt import QEventLoop, QThreadExecutor
from PyQt5.QtWidgets import QApplication, QMainWindow, QStatusBar, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QIcon
from lcu_driver import Connector
from ChampSelect import ChampSelect


class MainWindow(QMainWindow):
    def __init__(self, logger=None):
        super(MainWindow, self).__init__()

        self.setWindowTitle("League PhD")

        # browser
        self.web_view = WebView(self)
        self.setCentralWidget(self.web_view)

        # version
        try:
            with open('version.txt', 'r') as f:
                self.version = f.read()
        except FileNotFoundError:
            self.version = None

        # status bar: connection status
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.showMessage("Waiting for a connection...")

        # status bar: version status
        self.label_update = QLabel(f"{self.version} (latest) ")
        self.status_bar.addPermanentWidget(self.label_update)

        self.setStatusBar(self.status_bar)

        # check updates
        self.check_update()

        # logger
        self.logger = logger

        self.setWindowIcon(QIcon('assets/icon.ico'))

    def call_update(self, result_dict, dict_updated):
        self.logger.info('sent a call')
        result_dict['updated'] = dict_updated
        self.web_view.page().runJavaScript(f'app_call({json.dumps(result_dict)});')

    def go_to_pick_now(self):
        self.logger.info('redirect to pick now')
        self.web_view.page().runJavaScript(f'go_to_pick_now();')

    def check_update(self):
        try:
            latest_version = requests.get("https://api.github.com/repos/leaguephd/leaguephd-app/releases/latest").json()['tag_name']

            if self.version != latest_version:
                self.label_update.setText(f"Current: {self.version} (<a href=\"https://github.com/leaguephd/leaguephd-app/releases\">{latest_version} available</a>) ")
                self.label_update.setOpenExternalLinks(True)
        except KeyError:
            pass
        except requests.exceptions.ConnectionError:
            self.label_update.setText("Cannot connect to the file archive")


class WebView(QWebEngineView):
    def __init__(self, parent):
        super(WebView, self).__init__(parent)
        self.base_url = QUrl("https://www.leaguephd.com/stats/pick-now/")
        self.load(self.base_url)


def working():
    work_loop = asyncio.new_event_loop()
    connector = Connector(loop=work_loop)

    # fired when LCU API is ready to be used
    @connector.ready
    async def connect(connection):
        logger.info('LCU API is ready to be used.')
        window.status_bar.showMessage("Connected to the League client")

        # check whether session is in place
        session = await connection.request('get', '/lol-champ-select/v1/session')
        if session.status == 200:
            logger.info("session is already in place")
            logger.info(json.dumps(session.data))

            window.go_to_pick_now()
            champselect.reset()
            updated, dict_updated = champselect.update(session.data)
            if updated:
                window.call_update(champselect.__repr__(), dict_updated)
        else:
            logger.info("session is not in place")

    # fired when League Client is closed (or disconnected from websocket)
    @connector.close
    async def disconnect(_):
        logger.info('The client have been closed!')
        window.status_bar.showMessage("Waiting for a connection...")
        await connector.stop()
        sys.exit()

    # subscribe to '/lol-summoner/v1/session' endpoint
    @connector.ws.register('/lol-champ-select/v1/session', event_types=('CREATE', 'UPDATE', 'DELETE',))
    async def new_event(connection, event):
        if event.type == 'Create':
            logger.info("session created")
            logger.info(json.dumps(event.data))

            window.go_to_pick_now()
            champselect.reset()
        elif event.type == 'Update':
            logger.info(json.dumps(event.data))

            updated, dict_updated = champselect.update(event.data)
            if updated:
                window.call_update(champselect.__repr__(), dict_updated)

        elif event.type == 'Delete':
            logger.info("session deleted")

    connector.start()


async def main():
    with QThreadExecutor(1) as executor:
        await loop.run_in_executor(executor, working)


if __name__ == '__main__':
    # argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # logger
    logger = logging.getLogger()
    if args.debug:
        hdlr = logging.FileHandler('logs/session.log')
        logger.addHandler(hdlr)
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)

    # ChampSelect
    champselect = ChampSelect()

    # Qt
    app = QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(logger=logger)
    window.resize(1200, 850)
    window.show()

    try:
        with loop:
            loop.run_until_complete(main())
    except RuntimeError:
        pass
