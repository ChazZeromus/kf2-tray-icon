import wx, cairo, socket, struct, time, threading

ICONS = {
    'full':  'icon_full.png',
    'error': 'icon_error.png',
    'empty': 'icon_empty.png',
    'not_empty': 'icon_not_empty.png'
}

SERVER_ADDRESS    = '7.psycoframe.space'
SERVER_QUERY_PORT = 27015
LISTEN_PORT       = 24913

INTERVAL_SEC      = 60

STATUS_STR        = 'Server: {name}\nMap: {map}\nPlayers: {players}/{max_players}'


def create_menu_item(menu, label, func):
    item = wx.MenuItem(menu, -1, label)
    menu.Bind(wx.EVT_MENU, func, id=item.GetId())
    menu.AppendItem(item)
    return item

class IconRenderer(object):
    def __init__(self, **icon_dict):
        self.icon_surfaces = { k:cairo.ImageSurface.create_from_png(path) for k, path in icon_dict.iteritems() }

        surfaces_kv = list(self.icon_surfaces.iteritems())

        first_name, surface = surfaces_kv[0]
        self.width, self.height = surface.get_width(), surface.get_height()

        for k, surface in surfaces_kv[1:]:
            w = surface.get_width()
            h = surface.get_height()

            if w != self.width or h != self.height:
                raise Exception('All icons must be of same width! {} ({},{}) != {} ({}, {})'.format(
                    first_name, self.width, self.height, k, w, h
                ))

        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)

        self.context = cairo.Context(self.surface)

        self.bmp = wx.EmptyBitmap(self.width, self.height, 32)

        self.icon = None

    def _clear(self):
        c = self.context

        c.set_source_rgba(0, 0, 0, 0)
        c.rectangle(0, 0, self.width, self.height)
        c.fill()

    def _clear_with_icon(self, icon):
        c = self.context
        c.set_source_surface(self.icon_surfaces[icon])
        c.rectangle(0, 0, self.width, self.height)
        c.fill()

    def render(self, icon, text):
        self._clear_with_icon(icon)

        if text:
            c = self.context
            c.set_source_rgb(1, 1, 1)
            c.set_font_size(float(self.height) * 0.8)
            c.select_font_face('Courier New', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

            render_text(c, text, self.width / 2, self.height / 2)

    def update(self):
        data = str(self.surface.get_data())

        self.bmp.CopyFromBuffer(data, wx.BitmapBufferFormat_ARGB32)

        if self.icon is None:
            self.icon = wx.IconFromBitmap(self.bmp)
        else:
            self.icon.CopyFromBitmap(self.bmp)

    def get_icon(self):
        return self.icon

def render_text(c, text, x, y, align='middle'):
    x_b, y_b, w, h, x_a, y_a = c.text_extents(text)

    if align == 'middle':
        x -= w / 2
        y += h / 2
    elif align == 'topleft':
        y += h
    elif align == 'bottomright':
        x -= w
    elif align == 'middletop':
        x -= w / 2
        y += h
    elif align == 'middleleft':
        y += h / 2

    c.move_to(x, y)
    c.show_text(text)

class TaskBarIcon(wx.TaskBarIcon):
    EVT_UPDATE = wx.NewId()

    class UpdateEvent(wx.PyEvent):
        def __init__(self, data, error=False):
            wx.PyEvent.__init__(self)
            self.SetEventType(TaskBarIcon.EVT_UPDATE)
            self.data  = data
            self.error = error

    def __init__(self):
        super(TaskBarIcon, self).__init__()

        self.render = IconRenderer(**ICONS)

        self.Bind(wx.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)

        self.thread     = threading.Thread(target=self.thread_run)
        self.exit       = False
        self.last_error = None

        self.server_info = None

        self.Connect(-1, -1, self.EVT_UPDATE, self.on_update)

        self.update_icon(None)

        self.start_monitor()

    def CreatePopupMenu(self):
        menu = wx.Menu()
        create_menu_item(menu, 'Refresh', self.on_refresh)
        menu.AppendSeparator()
        create_menu_item(menu, 'Exit', self.on_exit)
        return menu

    def on_left_down(self, event):
        print 'Tray icon was left-clicked.'

    def on_refresh(self, event):
        self.last_trigger = time.time() - INTERVAL_SEC

    def on_update(self, event):
        self.update_icon(event.data, event.error)

    def update_icon(self, server_info, error=False):
        had_data = bool(self.server_info)

        self.server_info = server_info

        if error:
            players = '!'
            status  = 'Error: {}'.format(self.last_error)
            icon    = 'error'

        elif self.server_info is None:
            players = 0
            status  = 'Waiting for data...' if had_data else 'No data'
            icon    = 'error'
        else:
            players, max_players = self.server_info['players'], self.server_info['max_players']
            status  = STATUS_STR.format(**self.server_info)

            if not players:
                icon = 'empty'
            elif players < max_players:
                icon = 'not_empty'
            else:
                icon = 'full'

        self.render.render(icon, str(players))
        self.render.update()

        self.SetIcon(self.render.get_icon(), status)

    def start_monitor(self):
        self.thread.start()

    def on_exit(self, event):
        self.exit = True

        if self.thread.isAlive():
            self.thread.join()
        
        wx.CallAfter(self.Destroy)

    def thread_run(self):
        self.last_trigger = None

        MESSAGE = b'\xff\xff\xff\xff\x54Source Engine Query\x00'

        dest = (SERVER_ADDRESS, SERVER_QUERY_PORT)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        sock.bind(('', LISTEN_PORT))
        sock.setblocking(0)

        self.last_trigger = time.time() - INTERVAL_SEC

        print 'thread started, dest: {}, interval: {}'.format(dest, INTERVAL_SEC)

        while not self.exit: 
            time.sleep(0.001)

            if self.last_trigger is None:
                try:
                    data, src = sock.recvfrom(8192)
                    print 'received data:', repr(data)

                except socket.error:
                    pass

                except:
                    raise

                else:
                    self.last_trigger = time.time()

                    error       = False
                    server_info = None

                    try:
                        server_info = parse_a2sinfo_response(data)
                    except Exception as e:
                        error       = True
                        server_info = None

                        print 'Error {}'.format(e)
                        self.last_error = str(e)
                    finally:
                        wx.PostEvent(self, self.UpdateEvent(server_info, error))

            elif time.time() - self.last_trigger > INTERVAL_SEC:
                print 'sent packet'
                self.last_trigger = None
                sock.sendto(MESSAGE, dest)

        sock.close()

def main():
    app  = wx.PySimpleApp()
    TaskBarIcon()
    app.MainLoop()

def parse_a2sinfo_response(data):
    def seek_nullbyte_string(data):
        p = data.find('\x00')

        extracted = data[:p]

        return extracted, data[p + 1:] 

    unpack_fields = '<4sBB'
    unpack_size   = struct.calcsize(unpack_fields)
    magic, header, protocol = struct.unpack(unpack_fields, data[:unpack_size])

    data = data[unpack_size:]

    if magic != '\xff\xff\xff\xff':
        raise Exception('Bad magic: {}'.format(repr(magic)))

    server_info = {}

    if header != 0x49:
        raise Exception('Bad header: 0x{:X}'.format(header))


    server_info['name'], data = seek_nullbyte_string(data)

    server_info['map'], data  = seek_nullbyte_string(data)

    server_info['folder'], data = seek_nullbyte_string(data)

    server_info['game'], data = seek_nullbyte_string(data)

    unpack_fields = '>H7B'
    unpack_size   = struct.calcsize(unpack_fields)

    unpacked = struct.unpack(unpack_fields, data[:unpack_size])

    for i, field in enumerate(('id', 'players', 'max_players', 'bots', 'server_type', 'environment', 'visibility', 'vac')):
        server_info[field] = unpacked[i]

    data = data[unpack_size:]

    return server_info

def udp_test():
    UDP_IP = "7.psycoframe.space"

    UDP_PORT    = 27015
    LISTEN_PORT = 24913


    MESSAGE = '\xff\xff\xff\xff\x54Source Engine Query\x00'

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sock.bind(('', LISTEN_PORT))
    sock.setblocking(0)

    print "UDP target IP:", UDP_IP
    print "UDP target port:", UDP_PORT
    print "message:", MESSAGE

    sock.sendto(MESSAGE, (UDP_IP, UDP_PORT))

    while True:
        try:
            data, src = sock.recvfrom(8192) # buffer size is 1024 bytes
        except socket.error:
            time.sleep(0.001)
        except:
            raise
        else:
            print "received message:", repr(data)

            info = parse_a2sinfo_response(data)
            print info

if __name__ == '__main__':
    main()