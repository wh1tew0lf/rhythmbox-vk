# -*- coding: utf8 -*-
# Copyright © 2013 Radist Morse <radist.morse@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from gi.repository import RB, Gio, Gtk, GdkPixbuf, GObject, Peas, PeasGtk, WebKit2
from xml.dom import minidom  # xml parser
from xml.sax.saxutils import unescape  # xml unescape
import urllib.request, urllib.error, urllib.parse  # search line escaping, simple https requests

import gettext

gettext.install('rhythmbox', RB.locale_dir())


# entry type for results. not saving on disk
class VKEntryType(RB.RhythmDBEntryType):
    def __init__(self):
        RB.RhythmDBEntryType.__init__(self, name="vk-entry-type", save_to_disk=False)

    def can_sync_metadata(self, entry):
        return False

    def do_sync_metadata(self, entry, changes):
        return


class VKRhythmbox(GObject.Object, Peas.Activatable):
    __gtype_name = 'VKRhythmboxPlugin'
    object = GObject.property(type=GObject.GObject)

    def __init__(self):
        GObject.Object.__init__(self)

    def do_activate(self):
        print("activating vk plugin")
        # connecting to GSettings
        schema_source = Gio.SettingsSchemaSource.new_from_directory(self.plugin_info.get_data_dir(),
                                                                    Gio.SettingsSchemaSource.get_default(), False, )
        schema = schema_source.lookup('org.gnome.rhythmbox.plugins.vk', False)
        self.settings = Gio.Settings.new_full(schema, None, None)
        # system settings
        shell = self.object
        db = shell.props.db
        vk_entry_type = VKEntryType()
        self.entry_type = vk_entry_type
        db.register_entry_type(vk_entry_type)
        # icon
        iconfile = Gio.File.new_for_path(self.plugin_info.get_data_dir() + "/vk-symbolic.svg")
        # create Source (aka tab)
        self.source = GObject.new(VKSource, shell=shell,
                                  name="VK " + _("Music"),
                                  entry_type=vk_entry_type,
                                  plugin=self,
                                  icon=Gio.FileIcon.new(iconfile))
        self.source.setup(db, self.settings)
        shell.register_entry_type_for_source(self.source, vk_entry_type)
        # append source to the library
        group = RB.DisplayPageGroup.get_by_id("library")
        shell.append_display_page(self.source, group)

    def do_deactivate(self):
        print("deactivating vk plugin")
        self.source.delete_thyself()
        self.source = None
        self.settings = None
        self.entry_type = None


# Source is the tab, the "main window"
class VKSource(RB.BrowserSource):
    def __init__(self, **kwargs):
        super(VKSource, self).__init__(kwargs)

    # callbacks for monitoring GSettings change
    def on_token_changed(self, settings, key):
        self.TOKEN = settings.get_string(key)
        self.check_token()

    def on_api_id_changed(self, settings, key):
        self.API_ID = settings.get_string(key)

    def on_amount_changed(self, settings, key):
        self.AMOUNT = settings.get_int(key)
        self.search_amount.set_text(str(self.AMOUNT))

    def on_query_changed(self, settings, key):
        self.QUERY = settings.get_string(key)
        self.search_input.set_text(self.QUERY)

    def on_fuzzy_changed(self, settings, key):
        self.FUZZY = settings.get_boolean(key)
        self.search_fuzzy_checkbox.set_active(self.FUZZY)

    def setup(self, db, settings):
        self.initialised = False
        self.configured = False
        self.db = db
        self.settings = settings
        # initial GSettings values
        self.TOKEN = self.settings.get_string('token')
        self.API_ID = self.settings.get_string('api-id')
        self.AMOUNT = self.settings.get_int('amount')
        self.QUERY = self.settings.get_string('query')
        self.FUZZY = self.settings.get_boolean('fuzzy')
        self.CAPTCHA_PARAM = ""
        # monitoring callbacks
        self.settings.connect("changed::token", self.on_token_changed)
        self.settings.connect("changed::api-id", self.on_api_id_changed)
        self.settings.connect("changed::amount", self.on_amount_changed)
        self.settings.connect("changed::query", self.on_query_changed)
        self.settings.connect("changed::fuzzy", self.on_fuzzy_changed)
        # UI setup
        search_line = Gtk.HBox()
        self.search_input = Gtk.Entry(activates_default=True)
        self.search_input.set_text(self.QUERY)
        search_line.pack_start(self.search_input, expand=True, fill=True, padding=2)
        search_button = Gtk.Button(_("Search"))
        audios_button = Gtk.Button(_("Audios"))

        def click_search(a):
            search_button.clicked()

        self.search_input.connect("activate", click_search)
        search_line.pack_start(search_button, expand=False, fill=False, padding=2)
        search_line.pack_start(audios_button, expand=False, fill=False, padding=2)
        self.search_fuzzy_checkbox = Gtk.CheckButton.new_with_label(_("Autocomplete"))
        self.search_fuzzy_checkbox.set_margin_left(10)
        self.search_fuzzy_checkbox.set_active(self.FUZZY)
        search_line.pack_start(self.search_fuzzy_checkbox, expand=False, fill=False, padding=0)
        search_amount_label = Gtk.Label(_("#"))
        search_amount_label.set_margin_left(10)
        search_line.pack_start(search_amount_label, expand=False, fill=False, padding=0)
        self.search_amount = Gtk.Entry(width_chars=7, activates_default=True)
        self.search_amount.set_text(str(self.AMOUNT))
        self.search_amount.set_margin_right(10)
        self.search_amount.connect("activate", click_search)
        search_line.pack_start(self.search_amount, expand=False, fill=False, padding=0)
        clear_button = Gtk.Button(_("Clear"))
        search_line.pack_start(clear_button, expand=False, fill=False, padding=2)
        # buttons actions
        search_button.connect("clicked", self.search_button_clicked, self.search_input.get_text,
                              self.search_fuzzy_checkbox.get_active, self.search_amount.get_text)
        clear_button.connect("clicked", self.clear_button_clicked)
        audios_button.connect("clicked", self.audios_button_clicked, self.search_input.get_text,
                              self.search_fuzzy_checkbox.get_active, self.search_amount.get_text)

        search_line.show_all()
        # place "our" UI to the Source. Removing unneeded GtkToolbar.
        self.get_children()[0].get_children()[1].get_children()[1].hide()
        self.get_children()[0].get_children()[1].attach_next_to(search_line,
                                                                self.get_children()[0].get_children()[1].get_children()[
                                                                    0], Gtk.PositionType.LEFT, 3, 1)

    def do_selected(self):
        if not self.initialised:
            self.initialised = True
            self.check_token()

    def check_token(self):
        self.configured = False
        if (len(self.TOKEN) == 0):
            return
        xml = minidom.parseString(urllib.request.urlopen(
            "https://api.vk.com/method/users.isAppUser.xml?access_token=%s%s" % (
            self.TOKEN, self.CAPTCHA_PARAM)).read())
        self.CAPTCHA_PARAM = ""
        response = xml.getElementsByTagName("response")
        if not response or len(response) == 0 or response[0].firstChild.nodeValue != "1":
            error = xml.getElementsByTagName("error")
            err_code = int(error[0].getElementsByTagName("error_code")[0].firstChild.nodeValue)
            err_desc = str(error[0].getElementsByTagName("error_msg")[0].firstChild.nodeValue)
            if (err_code == 14):  # captcha
                captcha_sid = str(error[0].getElementsByTagName("captcha_sid")[0].firstChild.nodeValue)
                captcha_img = str(error[0].getElementsByTagName("captcha_img")[0].firstChild.nodeValue)
                cp_image = Gtk.Image()
                cp_response = urllib.request.urlopen(captcha_img)
                loader = GdkPixbuf.PixbufLoader.new_with_type('jpeg')
                loader.write(cp_response.read())
                loader.close()
                cp_image.set_from_pixbuf(loader.get_pixbuf())
                d = Gtk.Dialog(buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))
                cp_input = Gtk.Entry(width_chars=7, activates_default=True)
                d.vbox.pack_start(cp_image, expand=False, fill=False, padding=0)
                d.vbox.pack_start(cp_input, expand=False, fill=False, padding=0)
                d.show_all()
                d.run()
                cp_text = cp_input.get_text()
                d.destroy()
                if len(cp_text) > 0:
                    self.CAPTCHA_PARAM = "&captcha_sid=" + captcha_sid + "&captcha_key=" + cp_text
                    self.check_token()  # do the check till victory!
            return
        self.configured = True
        return

    def show_warning(self):
        d = Gtk.Dialog(buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))
        l = Gtk.Label("Incorrect vk-token.\nReconfigure your plugin.")
        d.vbox.pack_start(l, expand=False, fill=False, padding=0)
        d.show_all()
        d.run()
        d.destroy()

    def search_button_clicked(self, button, s_input, s_fuzzy, s_amount):
        if not self.configured:
            self.show_warning()
            return
        self.QUERY = s_input()
        self.settings.set_string("query", self.QUERY)
        self.FUZZY = "0"
        if s_fuzzy():
            self.FUZZY = "1"
        self.settings.set_boolean("fuzzy", s_fuzzy())
        try:
            self.AMOUNT = int(s_amount())
        except:
            self.AMOUNT = 100
        if (self.AMOUNT <= 0):
            self.AMOUNT = 100
        self.settings.set_int("amount", self.AMOUNT)
        # Only do anything if there is text in the search entry
        if len(self.QUERY) > 0:
            search = VkontakteSearch(self.QUERY, self.FUZZY, str(self.AMOUNT), self.db, self.props.entry_type,
                                     self.props.query_model, self.TOKEN)
            search.start()

    def audios_button_clicked(self, button, s_input, s_fuzzy, s_amount):
        if not self.configured:
            self.show_warning()
            return
        self.QUERY = s_input()
        self.settings.set_string("query", self.QUERY)
        self.FUZZY = "0"
        if s_fuzzy():
            self.FUZZY = "1"
        self.settings.set_boolean("fuzzy", s_fuzzy())
        try:
            self.AMOUNT = int(s_amount())
        except:
            self.AMOUNT = 100
        if (self.AMOUNT <= 0):
            self.AMOUNT = 100
        self.settings.set_int("amount", self.AMOUNT)
        # Only do anything if there is text in the search entry
        if len(self.QUERY) > 0:
            search = VkontakteSearch(self.QUERY, self.FUZZY, str(self.AMOUNT), self.db, self.props.entry_type,
                                     self.props.query_model, self.TOKEN)
            search.audios()

    def clear_button_clicked(self, button):
        # remove all VKEntryType entries from the db
        self.props.shell.props.db.entry_delete_by_type(self.props.entry_type)
        self.props.shell.props.db.commit()

    def do_impl_delete_thyself(self):
        if self.initialised:
            self.props.shell.props.db.entry_delete_by_type(self.props.entry_type)
            self.props.shell.props.db.commit()
        RB.Source.do_impl_delete_thyself(self)


GObject.type_register(VKSource)


class XMLResult:
    def __init__(self, entry):
        # Store the function. This will be called when we are ready to be added to the db.
        try:
            self.title = entry.getElementsByTagName('title')[0].firstChild.nodeValue.strip()
            self.duration = int(entry.getElementsByTagName('duration')[0].firstChild.nodeValue)
            self.artist = entry.getElementsByTagName('artist')[0].firstChild.nodeValue.strip()
            self.url = entry.getElementsByTagName('url')[0].firstChild.nodeValue
        except:
            self.url = None


class VkontakteSearch:
    def __init__(self, search_line, search_fuzzy, search_num, db, entry_type, query_model, TOKEN):
        self.search_line = search_line
        self.search_fuzzy = search_fuzzy
        self.search_num = search_num
        self.db = db
        self.entry_type = entry_type
        self.query_model = query_model
        self.entries_hashes = []
        self.TOKEN = TOKEN
        self.CAPTCHA_PARAM = ""

    def add_entry(self, result):
        if (not result.url):
            return
        # add only distinct songs (unique by title+artist+duration) to prevent duplicates
        strhash = ('%s%s%s' % (result.title, result.artist, result.duration)).lower()
        if strhash in self.entries_hashes:
            return

        self.entries_hashes.append(strhash)
        try:
            # first, let's try to find if the song with this url is already in db
            entry = self.db.entry_lookup_by_location(result.url)
            if entry is not None:
                return
            # add song to db
            entry = RB.RhythmDBEntry.new(self.db, self.entry_type, result.url)
            self.db.commit()
            if entry is not None:
                # update metadata
                self.db.entry_set(entry, RB.RhythmDBPropType.TITLE, unescape(result.title))
                self.db.entry_set(entry, RB.RhythmDBPropType.DURATION, result.duration)
                self.db.entry_set(entry, RB.RhythmDBPropType.ARTIST, unescape(result.artist))
                # all the songs will get "vk.com" album
                self.db.entry_set(entry, RB.RhythmDBPropType.ALBUM, "vk.com")
            self.db.commit()
        except Exception as e:  # This happens on duplicate uris being added
            sys.excepthook(*sys.exc_info())
            print("Couldn't add %s - %s" % (result.artist, result.title), e)

    # Get audios from user profile
    def audios(self):
        path = "https://api.vk.com/method/audio.get.xml?count=%s&access_token=%s%s" % (
        self.search_num, self.TOKEN, self.CAPTCHA_PARAM)
        data = urllib.request.urlopen(path).read()
        # vkontakte sometimes returns invalid XML with empty first line
        data = data.lstrip()
        xmldoc = minidom.parseString(data)
        error = xmldoc.getElementsByTagName("error")
        if (error) and len(error) > 0:
            err_code = int(error[0].getElementsByTagName("error_code")[0].firstChild.nodeValue)
            err_desc = str(error[0].getElementsByTagName("error_msg")[0].firstChild.nodeValue)
            if (err_code == 14):  # captcha
                captcha_sid = str(error[0].getElementsByTagName("captcha_sid")[0].firstChild.nodeValue)
                captcha_img = str(error[0].getElementsByTagName("captcha_img")[0].firstChild.nodeValue)
                cp_image = Gtk.Image()
                cp_response = urllib.request.urlopen(captcha_img)
                loader = GdkPixbuf.PixbufLoader.new_with_type('jpeg')
                loader.write(cp_response.read())
                loader.close()
                cp_image.set_from_pixbuf(loader.get_pixbuf())
                d = Gtk.Dialog(buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))
                cp_input = Gtk.Entry(width_chars=7, activates_default=True)
                d.vbox.pack_start(cp_image, expand=False, fill=False, padding=0)
                d.vbox.pack_start(cp_input, expand=False, fill=False, padding=0)
                d.show_all()
                d.run()
                cp_text = cp_input.get_text()
                d.destroy()
                if len(cp_text) > 0:
                    self.CAPTCHA_PARAM = "&captcha_sid=" + captcha_sid + "&captcha_key=" + cp_text
                    self.audios()  # try again till victory!
            return
        audios = xmldoc.getElementsByTagName("audio")
        if len(audios) == 0:
            count = xmldoc.getElementsByTagName("count")
            if len(count) > 0 and count[0].firstChild.nodeValue == "0":
                data = "No results found"
            # TODO: better way of showing this to user
            d = Gtk.Dialog()
            label = Gtk.Label(data)
            d.vbox.pack_start(label, True, True, 0)
            label.show_all()
            d.run()
            d.destroy()
        for audio in audios:
            self.add_entry(XMLResult(audio))

    # Starts searching
    def start(self):
        path = "https://api.vk.com/method/audio.search.xml?auto_complete=%s&count=%s&&q=%s&access_token=%s%s" % (
            self.search_fuzzy, self.search_num, urllib.parse.quote(self.search_line), self.TOKEN,
            self.CAPTCHA_PARAM)
        data = urllib.request.urlopen(path).read()
        # vkontakte sometimes returns invalid XML with empty first line
        data = data.lstrip()
        xmldoc = minidom.parseString(data)
        error = xmldoc.getElementsByTagName("error")
        if (error) and len(error) > 0:
            err_code = int(error[0].getElementsByTagName("error_code")[0].firstChild.nodeValue)
            err_desc = str(error[0].getElementsByTagName("error_msg")[0].firstChild.nodeValue)
            if (err_code == 14):  # captcha
                captcha_sid = str(error[0].getElementsByTagName("captcha_sid")[0].firstChild.nodeValue)
                captcha_img = str(error[0].getElementsByTagName("captcha_img")[0].firstChild.nodeValue)
                cp_image = Gtk.Image()
                cp_response = urllib.request.urlopen(captcha_img)
                loader = GdkPixbuf.PixbufLoader.new_with_type('jpeg')
                loader.write(cp_response.read())
                loader.close()
                cp_image.set_from_pixbuf(loader.get_pixbuf())
                d = Gtk.Dialog(buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))
                cp_input = Gtk.Entry(width_chars=7, activates_default=True)
                d.vbox.pack_start(cp_image, expand=False, fill=False, padding=0)
                d.vbox.pack_start(cp_input, expand=False, fill=False, padding=0)
                d.show_all()
                d.run()
                cp_text = cp_input.get_text()
                d.destroy()
                if len(cp_text) > 0:
                    self.CAPTCHA_PARAM = "&captcha_sid=" + captcha_sid + "&captcha_key=" + cp_text
                    self.start()  # try again till victory!
            return
        audios = xmldoc.getElementsByTagName("audio")
        if len(audios) == 0:
            count = xmldoc.getElementsByTagName("count")
            if len(count) > 0 and count[0].firstChild.nodeValue == "0":
                data = "No results found"
            # TODO: better way of showing this to user
            d = Gtk.Dialog()
            label = Gtk.Label(data)
            d.vbox.pack_start(label, True, True, 0)
            label.show_all()
            d.run()
            d.destroy()
        for audio in audios:
            self.add_entry(XMLResult(audio))


# The class which deals with config window
class VKRhythmboxConfig(GObject.Object, PeasGtk.Configurable):
    __gtype_name__ = 'VKRhythmboxConfig'
    object = GObject.property(type=GObject.GObject)

    def __init__(self):
        GObject.GObject.__init__(self)

    # the most interesting function, which is called when user presses "configure". should return a widget
    def do_create_configure_widget(self):
        # connect to GSettings
        schema_source = Gio.SettingsSchemaSource.new_from_directory(self.plugin_info.get_data_dir(),
                                                                    Gio.SettingsSchemaSource.get_default(), False, )
        schema = schema_source.lookup('org.gnome.rhythmbox.plugins.vk', False)
        self.settings = Gio.Settings.new_full(schema, None, None)
        self.API_ID = self.settings.get_string('api-id')
        self.TOKEN = self.settings.get_string('token')
        grid = Gtk.Grid()
        wv = WebKit2.WebView()
        wv.load_uri(
            "https://oauth.vk.com/oauth/authorize?client_id=%s&scope=audio,offline&redirect_uri=http://oauth.vk.com/blank.html&display=popup&response_type=token" % (
            self.API_ID))

        def uri_changed(webview, prop):
            url = webview.get_property(prop.name)
            if url.find("access_token") != -1:
                params = {key: value for key, value in [a.split("=") for a in url.split("#")[1].split("&")]}
                self.settings.set_string('token', params["access_token"])
                webview.get_toplevel().emit("close")

        wv.connect("notify::uri", uri_changed)
        grid.attach(wv, 0, 0, 1, 1)
        wv.set_size_request(550, 380)
        grid.show_all()
        return grid
