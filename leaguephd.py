import asyncio
import argparse
import json
import logging
import requests
import sys
from pathlib import Path
from qasync import QEventLoop, QThreadExecutor
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QStatusBar, QLabel
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QUrl, pyqtSignal
    from PyQt6.QtGui import QIcon, QDesktopServices
except ImportError:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QStatusBar, QLabel
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    from PyQt5.QtCore import QUrl, pyqtSignal
    from PyQt5.QtGui import QIcon, QDesktopServices
import aiohttp
from lcu_driver import Connector
from lcu_driver.connection import Connection
from ChampSelect import ChampSelect


async def _patched_wait_api_ready(self) -> None:
    while not self.closed:
        try:
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth('riot', self._auth_key),
                headers=self._headers
            ) as session:
                async with session.get(f'{self.address}/riotclient/region-locale', ssl=False) as _:
                    break
        except (aiohttp.ClientConnectorError, aiohttp.ClientError):
            await asyncio.sleep(0.5)


Connection._wait_api_ready = _patched_wait_api_ready


def resource_path(relative_path: str) -> Path:
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


DDRAGON_PATCH_JS = r"""
(function() {
    if (window.__lphd_ddragon_patched) return;
    if (typeof champion_data === 'undefined' || typeof $ === 'undefined') {
        setTimeout(arguments.callee, 200);
        return;
    }
    window.__lphd_ddragon_patched = true;

    const TAG_TO_ROLES = {
        'Marksman': ['ADC'],
        'Support': ['SUP'],
        'Mage': ['MID', 'SUP'],
        'Assassin': ['MID', 'JGL'],
        'Fighter': ['TOP', 'JGL'],
        'Tank': ['TOP', 'JGL', 'SUP']
    };

    const custom_champ_roles = {};

    fetch('https://ddragon.leagueoflegends.com/api/versions.json')
        .then(r => r.json())
        .then(versions => {
            const latest = versions[0];
            return fetch('https://ddragon.leagueoflegends.com/cdn/' + latest + '/data/en_US/champion.json')
                .then(r => r.json())
                .then(data => ({ latest, champs: data.data }));
        })
        .then(({ latest, champs }) => {
            const banContainer = $('#div-bans > div.d-flex');
            for (const [key, val] of Object.entries(champs)) {
                const cid = String(val.key);
                const roles = [];
                for (const t of (val.tags || [])) {
                    for (const r of (TAG_TO_ROLES[t] || [])) {
                        if (!roles.includes(r)) roles.push(r);
                    }
                }
                custom_champ_roles[cid] = roles.length ? roles : ['MID'];

                if (!champion_data[cid]) {
                    const iconUrl = 'https://ddragon.leagueoflegends.com/cdn/' + latest + '/img/champion/' + val.image.full;
                    const loadingUrl = 'https://ddragon.leagueoflegends.com/cdn/img/champion/loading/' + val.id + '_0.jpg';
                    champion_data[cid] = {
                        name: val.name,
                        portrait: iconUrl,
                        portrait_large: loadingUrl,
                        img_name: iconUrl,
                        img_name_large: loadingUrl,
                        is_custom_ddragon: true
                    };
                    if (banContainer.length && banContainer.find("input[value='" + cid + "']").length === 0) {
                        const label = $('<label class="btn p-0 m-0 ban" style="width:4rem;height:4rem">' +
                            '<input type="checkbox" name="bans" value="' + cid + '" id="id_bans_' + cid + '">' +
                            '<img src="' + iconUrl + '" style="width:100%;height:100%;vertical-align:baseline"></label>');
                        label.find('img').on('click', function() {
                            if ($(this).parent().hasClass("check")) {
                                $(this).parent().toggleClass("check");
                                for (let i = 0; i < bans.length; i++) {
                                    if (bans[i] === parseInt(cid)) {
                                        bans[i] = null;
                                        update_ban_portraits();
                                        break;
                                    }
                                }
                            } else {
                                for (let i = 0; i < bans.length; i++) {
                                    if (bans[i] === null) {
                                        bans[i] = parseInt(cid);
                                        $(this).parent().toggleClass("check");
                                        update_ban_portraits();
                                        break;
                                    }
                                }
                            }
                        });
                        banContainer.append(label);
                    }
                }
            }
            if (typeof update_ban_portraits === 'function' && phase === 'ban') {
                update_ban_portraits();
            }
        })
        .catch(err => console.error('Data Dragon sync error:', err));

    // Intercept $.ajax to support new champions in search and Lambda pick calculations
    const origAjax = $.ajax;
    $.ajax = function(options) {
        if (options && options.url === ajax_url_champion_search && options.data && options.data.champion_name) {
            const q = String(options.data.champion_name).trim().toLowerCase();
            for (const [cid, cinfo] of Object.entries(champion_data)) {
                if (parseInt(cid) > 0 && cinfo.name && cinfo.name.toLowerCase() === q) {
                    const fakeResp = { champion_id: parseInt(cid) };
                    if (options.success) options.success(fakeResp);
                    const d = $.Deferred();
                    d.resolve(fakeResp);
                    const p = d.promise();
                    p.always = function(cb) { cb(); return p; };
                    return p;
                }
            }
        }

        if (options && options.url === ajax_url && options.data) {
            try {
                const payload = JSON.parse(options.data);
                const newInsertList = [];
                if (Array.isArray(payload.insert_list)) {
                    for (const item of payload.insert_list) {
                        const cid = String(item.champion_id);
                        if (champion_data[cid] && champion_data[cid].is_custom_ddragon) {
                            let s = item.side;
                            let sl = item.slot;
                            if (s === null || sl === null) {
                                const po = find_pick_order();
                                if (po < 10) {
                                    s = get_side(po);
                                    sl = get_slot(po);
                                }
                            }
                            const defaultRole = item.role || ((custom_champ_roles[cid] && custom_champ_roles[cid][0]) || 'MID');
                            if (s !== null && sl !== null) {
                                payload.picks[s][sl] = {
                                    champion_id: parseInt(cid),
                                    role: defaultRole,
                                    role_manually_set: true
                                };
                                picks[s][sl] = {
                                    champion_id: parseInt(cid),
                                    role: defaultRole,
                                    role_manually_set: true
                                };
                            }
                        } else {
                            newInsertList.push(item);
                        }
                    }
                    payload.insert_list = newInsertList;
                    options.data = JSON.stringify(payload);
                }

                const origSuccess = options.success;
                if (origSuccess) {
                    options.success = function(json) {
                        if (json && Array.isArray(json.suggestions)) {
                            const pickedIds = new Set();
                            const bannedIds = new Set((bans || []).filter(x => x !== null && x !== -1));
                            const myTakenRoles = new Set();
                            if (Array.isArray(json.selected)) {
                                for (let side = 0; side < 2; side++) {
                                    for (let slot = 0; slot < 5; slot++) {
                                        const sc = json.selected[side][slot];
                                        if (sc && sc.champion_id && sc.champion_id !== -1) {
                                            pickedIds.add(parseInt(sc.champion_id));
                                            if (side === my_side && sc.role) myTakenRoles.add(sc.role);
                                        }
                                    }
                                }
                            }
                            for (const [cid, cinfo] of Object.entries(champion_data)) {
                                const numCid = parseInt(cid);
                                if (cinfo.is_custom_ddragon && !pickedIds.has(numCid) && !bannedIds.has(numCid)) {
                                    for (const r of (custom_champ_roles[cid] || ['MID'])) {
                                        if (!myTakenRoles.has(r)) {
                                            json.suggestions.push({
                                                champion: { id: numCid, role: r },
                                                popularity: 0.015,
                                                strength: 50.0,
                                                synergy: 50.0,
                                                counter: 50.0,
                                                risk: 3.0,
                                                score: {
                                                    score_composite: 5.0,
                                                    synergy: { positives: '', negatives: '' },
                                                    counter: { positives: '', negatives: '' },
                                                    tag_strength: 0,
                                                    tag_risk: 0,
                                                    tag_popularity: 0
                                                }
                                            });
                                        }
                                    }
                                }
                            }
                        }
                        return origSuccess.apply(this, arguments);
                    };
                }
            } catch (e) {
                console.error('Ajax patch error:', e);
            }
        }
        return origAjax.apply(this, arguments);
    };
})();
"""


class MainWindow(QMainWindow):
    sig_status_message = pyqtSignal(str)
    sig_call_update = pyqtSignal(object, object)
    sig_go_to_pick_now = pyqtSignal()
    sig_quit = pyqtSignal()

    def __init__(self, logger=None):
        super(MainWindow, self).__init__()

        self.setWindowTitle("League PhD")

        # signals for thread-safe GUI updates from the LCU worker thread
        self.sig_status_message.connect(self._on_status_message)
        self.sig_call_update.connect(self._on_call_update)
        self.sig_go_to_pick_now.connect(self._on_go_to_pick_now)
        self.sig_quit.connect(QApplication.instance().quit)

        # browser
        self.web_view = WebView(self)
        self.setCentralWidget(self.web_view)

        # version
        try:
            with open(resource_path('version.txt'), 'r') as f:
                self.version = f.read().strip()
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

        icon_file = 'assets/icon.icns' if sys.platform == 'darwin' and resource_path('assets/icon.icns').exists() else 'assets/icon.ico'
        self.setWindowIcon(QIcon(str(resource_path(icon_file))))

    def _on_status_message(self, message: str):
        self.status_bar.showMessage(message)

    def call_update(self, result_dict, dict_updated):
        self.sig_call_update.emit(result_dict, dict_updated)

    def _on_call_update(self, result_dict, dict_updated):
        self.logger.info('sent a call')
        result_dict['updated'] = dict_updated
        payload = json.dumps(result_dict)
        self.web_view.page().runJavaScript(DDRAGON_PATCH_JS)
        self.web_view.page().runJavaScript(f'''
            (function poll_app_call() {{
                if (typeof app_call === "function" && typeof $ !== "undefined") {{
                    app_call({payload});
                }} else {{
                    setTimeout(poll_app_call, 200);
                }}
            }})();
        ''')

    def go_to_pick_now(self):
        self.sig_go_to_pick_now.emit()

    def _on_go_to_pick_now(self):
        if self.web_view.page_loaded is not None and self.web_view.work_loop is not None:
            try:
                self.web_view.work_loop.call_soon_threadsafe(self.web_view.page_loaded.clear)
            except RuntimeError:
                pass

        self.logger.info('redirect to pick now')
        self.web_view.load(self.web_view.base_url)

    def check_update(self):
        try:
            latest_version = requests.get(
                "https://api.github.com/repos/leaguephd/leaguephd-app/releases/latest",
                timeout=5
            ).json()['tag_name']

            if self.version != latest_version:
                self.label_update.setText(f"Current: {self.version} (<a href=\"https://github.com/leaguephd/leaguephd-app/releases\">{latest_version} available</a>) ")
                self.label_update.setOpenExternalLinks(True)
        except (KeyError, requests.exceptions.RequestException):
            self.label_update.setText("Cannot connect to the file archive")


class WebView(QWebEngineView):
    def __init__(self, parent):
        super(WebView, self).__init__(parent)

        self.page_loaded = None
        self.work_loop = None
        self._initial_load_done = False
        self.base_url = QUrl("https://www.leaguephd.com/en/stats/pick-now/")
        self.loadProgress.connect(self.onLoadProgress)
        self.loadFinished.connect(self.onLoadFinished)
        self.load(self.base_url)

    def onLoadProgress(self, progress):
        if progress >= 80:
            self.page().runJavaScript(DDRAGON_PATCH_JS)
            self._mark_ready()

    def onLoadFinished(self, ok=True):
        self.page().runJavaScript(DDRAGON_PATCH_JS)
        self._mark_ready()

    def _mark_ready(self):
        self._initial_load_done = True
        if self.page_loaded is not None and self.work_loop is not None:
            try:
                self.work_loop.call_soon_threadsafe(self.page_loaded.set)
            except RuntimeError:
                pass

    def createWindow(self, _type):
        webview = WebView(self.parent())
        webview.urlChanged.connect(self.open_browser)
        return webview

    def open_browser(self, url):
        webview = self.sender()
        QDesktopServices.openUrl(url)
        webview.deleteLater()

    def is_pick_now(self):
        # check if the current page is Pick Now
        parts = self.url().path().rsplit('/', 2)
        return len(parts) >= 2 and parts[1] == 'pick-now'


def working():
    work_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(work_loop)
    connector = Connector(loop=work_loop)

    # to make sure the page has been loaded before running a JS script
    page_loaded = asyncio.Event()
    window.web_view.work_loop = work_loop
    window.web_view.page_loaded = page_loaded
    if window.web_view._initial_load_done:
        page_loaded.set()

    # fired when LCU API is ready to be used
    @connector.ready
    async def connect(connection):
        logger.info('LCU API is ready to be used.')
        window.sig_status_message.emit("Connected to the League client")

        # check whether session is in place
        resp = await connection.request('get', '/lol-champ-select/v1/session')
        await page_loaded.wait()
        if resp.status == 200:
            data = await resp.json()
            logger.info("session is already in place")
            logger.info(data)

            if not window.web_view.is_pick_now():
                window.go_to_pick_now()
                await page_loaded.wait()

            champselect.reset()
            updated, dict_updated = champselect.update(data)
            logger.info(champselect)
            if updated:
                window.call_update(champselect.__repr__(), dict_updated)
        else:
            logger.info("session is not in place")

    # fired when League Client is closed (or disconnected from websocket)
    @connector.close
    async def disconnect(_):
        logger.info('The client have been closed!')
        window.sig_status_message.emit("Waiting for a connection...")

    # subscribe to '/lol-champ-select/v1/session' endpoint
    @connector.ws.register('/lol-champ-select/v1/session', event_types=('CREATE', 'UPDATE', 'DELETE',))
    async def new_event(connection, event):
        if event.type == 'Create':
            logger.info("session created")
            logger.info(json.dumps(event.data))

            window.go_to_pick_now()
            champselect.reset()
            await page_loaded.wait()

        elif event.type == 'Update':
            if not window.web_view.is_pick_now():
                window.go_to_pick_now()
                champselect.reset()

            logger.info(json.dumps(event.data))
            updated, dict_updated = champselect.update(event.data)
            await page_loaded.wait()
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
    args, _ = parser.parse_known_args()

    # logger
    logger = logging.getLogger()
    if args.debug:
        log_dir = Path.home() / 'Library' / 'Logs' / 'LeaguePhD' if sys.platform == 'darwin' else Path('logs')
        log_dir.mkdir(parents=True, exist_ok=True)
        hdlr = logging.FileHandler(log_dir / 'session.log')
        logger.addHandler(hdlr)
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)

    # ChampSelect
    champselect = ChampSelect()

    # Qt
    app = QApplication(sys.argv)
    app.setApplicationName("League PhD")
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(logger=logger)
    window.resize(1200, 930)
    window.show()

    try:
        with loop:
            loop.run_until_complete(main())
    except RuntimeError:
        pass
