import wx, cairo, socket, struct, time, threading, sys, os

ICONS = {
	'full':  'icon_full.png',
	'error': 'icon_error.png',
	'empty': 'icon_empty.png',
	'not_empty': 'icon_not_empty.png'
}

NUMBER_ICON = 'number_ball.png'

SERVER_ADDRESS    = '7.psycoframe.space'
SERVER_QUERY_PORT = 27015
LISTEN_PORT       = 24913
TEXT_COLOR        = {
	'full'      : (1, 1, 1, 1),
	'error'     : (1, 1, 1, 1),
	'empty'     : (1, 1, 1, 1),
	'not_empty' : (1, 0, 0, 1)
}
TEXT_OPTIONS = ('Courier Regular', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

INTERVAL_SEC      = 60

STATUS_STR        = 'Server: {name}\nMap: {map}\nPlayers: {players}/{max_players}'
ICON_STR          = '{}'
#ICON_STR          = ''



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

		self.number_icon = cairo.ImageSurface.create_from_png(NUMBER_ICON)


	def _clear(self):
		c = self.context

		c.set_source_rgba(0, 0, 0, 0)
		c.paint()

	def _clear_with_icon(self, icon):
		c = self.context
		c.set_source_surface(self.icon_surfaces[icon])
		c.paint()

	def render(self, icon, text):
		self._clear_with_icon(icon)

		if text:
			c = self.context

			w, h = self.number_icon.get_width(), self.number_icon.get_height()

			c.translate(self.width - w, self.height - h)

			c.set_source_surface(self.number_icon)
			c.rectangle(0, 0, w, h)
			c.fill()

			c.identity_matrix()

			color = TEXT_COLOR.get(icon, (1, 1, 1, 1))

			c.set_source_rgba(*color)
			c.set_font_size(h)
			c.select_font_face(*TEXT_OPTIONS)

			render_text(c, text, self.width - (w / 2), self.height - (h / 2))

	def update(self):
		data = str(self.surface.get_data())

		self.bmp.CopyFromBuffer(data, wx.BitmapBufferFormat_ARGB32)

		if self.icon is None:
			self.icon = wx.IconFromBitmap(self.bmp)
		else:
			self.icon.CopyFromBitmap(self.bmp)

	def resize_to(self, surface):
		c = cairo.Context(surface)

		imgpat = cairo.SurfacePattern(self.surface)
		imgpat.set_filter(cairo.FILTER_BEST)

		m = cairo.Matrix()
		m.scale(surface.width() / float(self.width), surface.height() / float(self.height))

		c.set_matrix(m)
		c.set_source(imgpat)

		c.paint()


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
		def create_menu_item(menu, label, func=None):
			item = wx.MenuItem(menu, -1, label)

			if func is not None:
				menu.Bind(wx.EVT_MENU, func, id=item.GetId())

			menu.AppendItem(item)

			return item

		menu = wx.Menu()

		create_menu_item(menu, 'Refresh', self.on_refresh)

		menu.AppendSeparator()

		if self.server_info:
			items = [
				'Map: ' + self.server_info['map'],
				'Name: ' + self.server_info['name'],
				'Players: {}/{}'.format(self.server_info['players'], self.server_info['max_players'])
			]

			for line in items:
				create_menu_item(menu, line).Enable(False)

			if self.server_info['player_list']:
				menu.AppendSeparator()
				create_menu_item(menu, 'Players:').Enable(False)

				for index, player in enumerate(self.server_info['player_list'], 1):
					create_menu_item(menu, '{}. {}'.format(index, player['name'])).Enable(False)

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
			players = '?'
			status  = 'Waiting for data...' if had_data else 'No data'
			icon    = 'error'
		else:
			players, max_players = self.server_info['players'], self.server_info['max_players']

			copy = dict(self.server_info)

			copy['player_list'] = '\n'.join(
				'{}. {}'.format(index, player['name']) \
				for index, player in enumerate(self.server_info['player_list'], 1)
			)

			status  = STATUS_STR.format(**copy)

			print 'status string', status

			if not players:
				icon = 'empty'
			elif players < max_players:
				icon = 'not_empty'
			else:
				icon = 'full'

			if players == 0:
				players = ''

		self.render.render(icon, ICON_STR.format(players))
		self.render.update()

		self.SetIcon(self.render.get_icon(), status)

	def start_monitor(self):
		self.thread.start()

	def on_exit(self, event):
		wx.CallAfter(self.Destroy)

	def Destroy(self, *args):
		self.exit = True

		if self.thread.isAlive():
			self.thread.join()
		
		super(TaskBarIcon, self).Destroy(*args)

	def thread_run(self):
		self.last_trigger = None

		MESSAGE = b'\xff\xff\xff\xff\x54Source Engine Query\x00'

		dest = (SERVER_ADDRESS, SERVER_QUERY_PORT)

		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

		sock.bind(('', LISTEN_PORT))
		sock.setblocking(0)

		self.last_trigger = time.time() - INTERVAL_SEC

		print 'thread started, dest: {}, interval: {}'.format(dest, INTERVAL_SEC)

		state     = 0
		last_send = time.time()
		max_wait  = 5

		server_info = None

		while not self.exit: 
			time.sleep(0.001)

			if self.last_trigger is None:
				if time.time() - last_send < max_wait:
					try:
						data, src = sock.recvfrom(8192)
						print 'state:', state
						print 'received data:', repr(data)

					except socket.error:
						pass

					except:
						raise

					else:
						error = False

						try:
							if state == 0:
								server_info = parse_a2sinfo_response(data)
								server_info['player_list'] = []

								sock.sendto(b'\xff\xff\xff\xff\x55\xff\xff\xff\xff', dest)
								last_send = time.time()

							elif state == 1:
								_, header, challenge = struct.unpack('<LBL', data)

								if header != 0x41:
									raise Exception('Invalid a2s_player response header: 0x{:X}'.format(header))

								print 'got challenge:', challenge

								sock.sendto(struct.pack('<4sBL', b'\xff\xff\xff\xff', 0x55, challenge), dest)
								last_send = time.time()

							elif state == 2:
								players = parse_a2splayer_response(data)

								server_info['player_list'] = players

								print 'players', players

						except Exception as e:
							error       = True
							server_info = None
							state       = 2

							print 'Error {}'.format(e)
							self.last_error = str(e)

						finally:
							if state < 2:
								state += 1
							else:
								self.last_trigger = time.time()
								wx.PostEvent(self, self.UpdateEvent(server_info, error))
								server_info = None
								state       = 0
				else:
					self.last_trigger = time.time() - INTERVAL_SEC

			elif time.time() - self.last_trigger > INTERVAL_SEC:
				print 'sent packet'
				self.last_trigger = None
				last_send         = time.time()
				state             = 0

				sock.sendto(MESSAGE, dest)

		sock.close()

		print 'Thread closed'

class App(wx.PySimpleApp):
	def OnInit(self, *args, **kwargs):
		self.name = "TrayIcon-{}".format(wx.GetUserId())
		self.instance = wx.SingleInstanceChecker(self.name)

		if self.instance.IsAnotherRunning():
			wx.MessageBox('Another instance is running', 'ERROR')
			return False

		TaskBarIcon()

		return super(App, self).OnInit(*args, **kwargs)

def main():
	app = App()
	app.MainLoop()

def seek_nullbyte_string(data):
	p = data.find('\x00')

	extracted = data[:p]

	return extracted, data[p + 1:] 

def parse_a2splayer_response(data):
	_, header, players = struct.unpack('<LBB', data[:6])
	data = data[6:]

	if header != 0x44:
		raise Exception('Invalid a2s_player list response header: 0x{:X}'.format(header))

	result = []

	for _ in xrange(players):
		index, = struct.unpack('<B', data[:1])
		data = data[1:]

		name, data = seek_nullbyte_string(data)

		score, duration = struct.unpack('<Lf', data[:8])
		data = data[8:]

		result.append({
			'index': index,
			'name': name,
			'score': score,
			'duration': duration
		})

	# Index seems to be zero all the time for some reason
	'''
	def sort_func(a, b):
		return a['index'] - b['index']

	result.sort(sort_func)
	'''

	return result

def parse_a2sinfo_response(data):

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

class UnbufferedFile(object):
	def __init__(self, file_obj):
		self._file_obj = file_obj

		for attr in dir(file_obj):
			if not attr.startswith('_') and not hasattr(self, attr):
				setattr(self, attr, getattr(file_obj, attr))

	def write(self, *args):
		# value = self._file_obj.write(*args)
		# self.flush()

		# return value
		pass

if __name__ == '__main__':
	image, ext = os.path.splitext(os.path.basename(sys.executable))

	# Weird bug in pythonw where I think stdout.write calls cause
	# wx messages to not be processed if there is no console because
	# of wx trying to make text windows for each write.
	
	if image.lower() == 'pythonw':
		sys.stdout = UnbufferedFile(object())

	main()