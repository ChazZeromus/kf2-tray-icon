import wx, cairo

TRAY_TOOLTIP = 'System Tray Demo'
TRAY_ICON = 'icon.png'


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

        c = self.context

        c.set_source_rgb(1, 1, 1)
        c.set_font_size(float(self.height) * 0.8)
        c.select_font_face('Courier New', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        
        render_text(c, text, self.width / 2, self.height / 2)

    def update(self):
        data = str(self.surface.get_data())
        self.bmp.CopyFromBuffer(data, wx.BitmapBufferFormat_ARGB32)

    def get_bitmap(self):
        return self.bmp

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
    def __init__(self):
        super(TaskBarIcon, self).__init__()

        self.render = IconRenderer(main='icon.png')

        self.set_icon(TRAY_ICON)
        self.Bind(wx.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)


    def CreatePopupMenu(self):
        menu = wx.Menu()
        create_menu_item(menu, 'Say Hello', self.on_hello)
        menu.AppendSeparator()
        create_menu_item(menu, 'Exit', self.on_exit)
        return menu

    def set_icon(self, path):
        # icon = wx.IconFromBitmap(wx.Bitmap(path))

        self.render.render('main', '0')
        self.render.update()

        self.SetIcon(wx.IconFromBitmap(self.render.get_bitmap()), TRAY_TOOLTIP)

    def on_left_down(self, event):
        print 'Tray icon was left-clicked.'

    def on_hello(self, event):
        print 'Hello, world!'

    def on_exit(self, event):
        wx.CallAfter(self.Destroy)


def main():
    app = wx.PySimpleApp()
    TaskBarIcon()
    app.MainLoop()


if __name__ == '__main__':
    main()