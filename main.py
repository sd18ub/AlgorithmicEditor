import curses, _curses
import string
import sys
import pyperclip
from functools import partial
import os
import importlib

from utils import display_menu, input_text, get_screen_middle_coords, browse_files

# TODO Open .algo files in the editor by default on Linux
class App:
	def __init__(self, command_symbol: str = ":", using_namespace_std: bool = False, logs: bool = True):
		self.current_text = ""  # The text being displayed in the window
		self.stdscr : _curses.window = None  # The standard screen (see curses library)
		self.rows, self.cols = 0, 0  # The number of rows and columns in the window
		self.lines = 1  # The number of lines containing text in the window
		self.current_index = 0  # The current index of the cursor
		self.commands = {
			"q": (self.quit, "Quit", False),
			"c": (self.compile, "Compile", False),
			"t": (self.modify_tab_char, "Modify tab char", True),
			"s": (self.save, "Save", False),
			"qs": (partial(self.save, quick_save=True), "Quicksave", False),
			"o": (self.open, "Open", False),
			"p": (self.compile_to_cpp, "Compile to C++", False),
			"j": (self.toggle_std_use, "Toggle namespace std", True),
			"h": (self.display_commands, "Commands list", False),
			"cl": (self.clear_text, "Clear editor", True),
			"is": (self.insert_text, "Insert file", True),
			# To add the command symbol to the text
			command_symbol: (partial(self.add_char_to_text, command_symbol), command_symbol, True)
		}  # A dictionary of all the commands, either built-in or plugin-defined.
		self.instructions_list = []  # The list of instructions for compilation, is only used by the compilation functions
		self.tab_char = "\t"  # The tab character
		self.command_symbol = command_symbol  # The symbol triggering a command
		self.using_namespace_std = using_namespace_std  # Whether to use the std namespace during the C++ compilation
		self.logs = logs  # Whether to log
		self.min_display_line = 0  # The minimum line displayed on the window (scroll)
		self.cur = tuple()  # The cursor
		self.min_display_char = 0  # Useless at the moment
		self.last_save_action = "clipboard"  # What the user did the last time he saved some code from the editor ; can be 'clipboard' or the pah to a file.

		# Preparing the color pairs
		self.color_pairs = {
			"statement": 1,
			"function": 2,
			"variable": 3,
			"instruction": 4,
			"strings": 3
		}  # The number of the color pairs
		self.color_control_flow = {
			"statement": ("if", "else", "end", "elif", "for", "while", "switch", "case", "default", "const"),
			"function": ("fx", "fx_start", "return"),
			"variable": ('int', 'float', 'string', 'bool', 'char'),
			"instruction": ("print", "input", "arr")
		}  # What each type of statement corresponds to

		# Loads all the plugins
		self.plugins = self.load_plugins()  # A dict containing all the plugins as list of [module, instance]


	def main(self, stdscr: _curses.window):
		"""
		The main function, wrapped around by curses.
		"""
		# Curses initialization
		self.stdscr : _curses.window = stdscr
		self.stdscr.clear()
		self.rows, self.cols = self.stdscr.getmaxyx()

		# If a .crash file exists, we show a message asking if they want their data to be recovered,
		# then we set current_text to its contents and delete it
		if ".crash" in os.listdir(os.path.dirname(__file__)) and "--file" not in sys.argv:
			def recover_crash_data():
				with open(os.path.join(os.path.dirname(__file__), ".crash"), "r", encoding="utf-8") as f:
					self.current_text = f.read()
				self.display_text()

			display_menu(
				self.stdscr,
				(
					("Yes", recover_crash_data),
					("No", lambda: None)
				),
				label = "Data has been found from the last crash. Do you want to recover it ?",
				clear = False
			)
			os.remove(os.path.join(os.path.dirname(__file__), ".crash"))

		self.apply_stylings()
		self.stdscr.refresh()

		# Declaring the color pairs
		curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
		curses.init_pair(2, curses.COLOR_BLUE, curses.COLOR_BLACK)
		curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
		curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
		curses.init_pair(5, curses.COLOR_GREEN, curses.COLOR_BLACK)

		# Initializes each plugin, if they have an init function
		msg_string = "Loaded plugin {}"
		for i, (plugin_name, plugin) in enumerate(self.plugins.items()):
			if hasattr(plugin[1], "init"):
				plugin[1].init()
			# Writes a message to the screen showing all imported plugins
			self.stdscr.addstr(
				self.rows - 4 - i,
				self.cols - (len(msg_string.format(plugin_name)) + 2),
				msg_string.format(plugin_name)
			)
		msg_string = "Loaded {} plugins"
		self.stdscr.addstr(
			self.rows - 4 - len(self.plugins.keys()),
			self.cols - (len(msg_string.format(len(self.plugins.keys()))) + 2),
			msg_string.format(len(self.plugins.keys())), curses.color_pair(3)
		)
		del msg_string

		# Displays the text
		self.display_text()

		# App main loop
		while True:
			# Gets the current screen size
			self.rows, self.cols = self.stdscr.getmaxyx()

			# Key input
			key = self.stdscr.getkey()

			# If system key is pressed
			if key == self.command_symbol:
				self.stdscr.addstr(self.rows - 1, 0, self.command_symbol)
				key = input_text(self.stdscr, 1, self.rows - 1)
				if key in self.commands.keys():
					key_name, (function, name, hidden) = key, self.commands[key]
					self.stdscr.addstr(self.rows - 1, 1, key_name)
					try:
						function()
					except curses.error as e:
						self.stdscr.addstr(self.rows - 1, 5, "A curses error occured")
						self.log(e)
				self.stdscr.addstr(self.rows - 1, 0, " " * 4)
			# If it is a regular key
			else:
				# Screen clearing
				self.stdscr.clear()

				# If the key IS a backspace character, we remove the last character from the text
				if key in ("\b", "\0") or key.startswith("KEY_") or key.startswith("CTL_") or len(key) != 1:
					if key in ("KEY_BACKSPACE", "\b", "\0"):
						if self.current_index > 0:
							self.current_text = self.current_text[:self.current_index - 1] + self.current_text[self.current_index:]
							self.current_index -= 1
					elif key == "KEY_DC":
						if self.current_index < len(self.current_text):
							self.current_text = self.current_text[:self.current_index] + self.current_text[self.current_index+1:]
					elif key in ("KEY_UP", "KEY_DOWN"):
						text = self.current_text + "\n"
						indexes = tuple(index for index in range(len(text)) if text.startswith('\n', index))
						closest_index = min(indexes, key=lambda x:abs(x-self.current_index))
						closest_index = indexes.index(closest_index)
						closest_index = closest_index + (-1)**(key == "KEY_UP")
						try:
							if closest_index <= 0:
								self.current_index = 0
							else:
								self.current_index = indexes[closest_index]
						except IndexError: pass
					elif key == "KEY_LEFT":
						self.current_index -= 1
					elif key == "KEY_RIGHT":
						self.current_index += 1
					elif key == "CTL_LEFT":
						self.current_index -= 1
						while self.current_index >= 0 and self.current_text[self.current_index] in string.ascii_letters:
							self.current_index -= 1
					elif key == "CTL_RIGHT":
						self.current_index += 1
						while self.current_index < len(self.current_text) and self.current_text[self.current_index] in string.ascii_letters:
							self.current_index += 1
					elif key == "KEY_NPAGE":
						self.min_display_line -= 1
						if self.min_display_line < 0:
							self.min_display_line = 0
					elif key == "KEY_PPAGE":
						self.min_display_line += 1
						if self.min_display_line > self.lines - 1:
							self.min_display_line = self.lines - 1
					elif key == "KEY_F(1)":
						self.commands["h"][0]()
					elif key == "KEY_F(4)":
						self.commands["q"][0]()
					"""elif key == "KEY_HOME":
						self.min_display_char -= 1
						if self.min_display_char < 0:
							self.min_display_char = 0
					elif key == "KEY_END":
						self.min_display_char += 1"""
				else:
					# If the key is NOT a backspace character, we add the new character to the text
					self.add_char_to_text(key)

				# Calls the plugins update_on_keypress function
				for plugin in self.plugins.values():
					if hasattr(plugin[1], "update_on_keypress"):
						plugin[1].update_on_keypress(key)

				# Clamping the index
				self.current_index = max(min(self.current_index, len(self.current_text)), 0)

			# Displays the current text
			# TODO Longer lines
			self.display_text()

			# Visual stylings, e.g. adds a full line over the input
			self.apply_stylings()

			# Screen refresh after input
			self.stdscr.refresh()


	def quit(self) -> None:
		"""
		Exits the app.
		"""
		def quit():
			sys.exit(0)
		def save_and_quit():
			self.save()
			quit()
		def cancel():
			pass

		# Provides the option to save and quit, quit without saving, or cancel quitting.
		display_menu(
			self.stdscr,
			(
				("Quit without Saving", quit),
				("Save and Quit", save_and_quit),
				("Cancel", cancel)
			),
			1, "-- QUIT --"
		)


	def display_text(self):
		"""
		Displays the text in current_text.
		"""
		idx = 0
		self.cur = tuple()
		for i, line in enumerate(
				self.current_text.split("\n")[self.min_display_line:self.min_display_line + (self.rows - 3)]):
			line = line[self.min_display_char:]
			# Getting the splitted line for syntax highlighting
			splitted_line = line.split(" ")

			# Getting the cursor position
			if idx + len(line) > self.current_index and idx <= self.current_index:
				self.cur = (i - self.min_display_line, len(str(self.lines)) + 1 + (self.current_index - idx),
				            line[self.current_index - idx])
			elif idx + len(line) == self.current_index:
				self.cur = (i - self.min_display_line, len(str(self.lines)) + 1 + (self.current_index - idx), " ")

			# Writing the line to the screen
			if len(str(self.lines)) + 1 + len(line) < self.cols:
				# If the line's length does not overflow off the screen, we write it entirely
				self.stdscr.addstr(i, len(str(self.lines)) + 1, line)
			else:
				# If the line's length overflows off the screen, we write only the part that stays in the screen
				self.stdscr.addstr(i, len(str(self.lines)) + 1, line[:self.cols - (len(str(self.lines)) + 1)])

			# Updating the amount of characters in the line
			idx += len(line) + 1 + self.min_display_char

			# Tests the beginning of the line to add a color, syntax highlighting
			self.syntax_highlighting(line, splitted_line, i)

			# Calls the plugins update_on_syntax_highlight function
			for plugin_name, plugin in tuple(self.plugins.items()):
				if len(plugin) > 1:
					if hasattr(plugin[1], "update_on_syntax_highlight"):
						plugin[1].update_on_syntax_highlight(line, splitted_line, i)
				else:
					del self.plugins[plugin_name]

		# Placing cursor
		if self.cur != tuple() and self.cur[1] < self.cols:
			try:
				self.stdscr.addstr(*self.cur, curses.A_REVERSE)
			except curses.error:
				pass


	def apply_stylings(self) -> None:
		"""
		Apply all the stylings to the screen.
		"""
		# Applies the bar at the bottom of the screen
		try:
			self.stdscr.addstr(self.rows - 3, 0, "▓" * self.cols)
		except curses.error: pass

		# Adds the commands list at the bottom of the screen
		cols = 0
		for key_name, (function, name, hidden) in self.commands.items():
			if key_name != self.command_symbol and hidden is False:
				generated_str = f"{self.command_symbol}{key_name} - {name}"

				# If printing this text would overflow off the screen, we break out of the loop
				if cols + len(generated_str) >= self.cols + 4:
					try:
						self.stdscr.addstr(self.rows - 2, cols, "...", curses.A_REVERSE)
					except curses.error: pass
					# We also display "..." beforehand.
					break

				try:
					# Adds the generated string at the right place of the screen
					self.stdscr.addstr(self.rows - 2, cols, generated_str, curses.A_REVERSE)
					# Keeping in mind the x coordinates of the next generated string
					cols += len(generated_str)
					# Followed by a space
					self.stdscr.addstr(self.rows - 2, cols, " ")
				except curses.error:
					self.log(f"Could not display command {self.command_symbol}{key_name} - {name}")
				cols += 1

			# Adds a spacing between built-in and plugin commands
			elif key_name == self.command_symbol:
				cols += 3

		self.stdscr.refresh()

		# Gets the amount of lines in the text
		self.calculate_line_numbers()
		# Puts the line numbers at the edge of the screen
		for i in range(self.min_display_line, min(self.lines, self.min_display_line+(self.rows-3))):
			self.stdscr.addstr(i - self.min_display_line, 0, str(i + 1).zfill(len(str(self.lines))), curses.A_REVERSE)


	def load_plugins(self):
		"""
		Loads all the plugins.
		"""
		# Creating the plugins folder if it does not exist
		if not os.path.exists(os.path.join(os.path.dirname(__file__), "plugins")):
			os.mkdir(os.path.join(os.path.dirname(__file__), "plugins"))

		# Initializing the plugins var
		plugins = {}

		# Lists all the plugin files inside the plugins folder
		for plugin in os.listdir(os.path.join(os.path.dirname(__file__), "plugins")):
			if plugin.startswith("__") or os.path.isdir(os.path.join(os.path.dirname(__file__), "plugins", plugin)) \
					or not plugin.endswith(".py"):
				continue  # Python folders/files

			# Cleaning the name
			plugin = plugin.replace(".py", "")

			# Importing the plugin and storing it in the variable
			try:
				plugins[plugin] = [importlib.import_module(f"plugins.{plugin}")]
			except Exception as e:
				self.log(f"Failed to load plugin {plugin} :\n{e}")
				continue

			# Initializes the plugins init function
			try:
				plugins[plugin].append(plugins[plugin][0].init(self))
			except Exception as e:
				del plugins[plugin]
				self.log(f"An error occurred while importing the plugin '{plugin}' :\n{e}")

		# Returning the dict of plugins
		return plugins


	def calculate_line_numbers(self) -> int:
		"""
		Calculates the amount of lines in the text.
		Saves it into the correct variable and returns it.
		"""
		self.lines = self.current_text.count("\n") + 1
		return self.lines


	def modify_tab_char(self) -> None:
		"""
		Modifies the tab character.
		"""
		self.tab_char = input_text(self.stdscr, position_x=3)


	def clear_text(self):
		"""
		Clears the current text in the editor.
		"""
		def _clear_text():
			self.current_text = ""
			self.current_index = 0

		display_menu(self.stdscr, (
			("Yes", _clear_text),
			("No", lambda: None)
		),
		label="Confirm clearing editor ?")


	def insert_text(self):
		"""
		Inserts the text from the given file into the editor
		"""
		filename = browse_files(self.stdscr, can_create_files=False)()
		if filename != "":
			with open(filename, "r", encoding="utf-8") as f:
				self.add_char_to_text(f.read())


	def add_char_to_text(self, key: str):
		"""
		Adds the given character at the end of the text.
		:param key: A character to add to the text.
		"""
		self.current_text = self.current_text[:self.current_index] + key + self.current_text[self.current_index:]
		self.current_index += len(key)


	def display_commands(self):
		"""
		Displays all the commands at the center of the screen.
		"""
		# Gets the middle screen coordinates
		middle_y, middle_x = get_screen_middle_coords(self.stdscr)

		# Creates the label
		generated_str = "----- Commands list -----"
		self.stdscr.addstr(
			middle_y - len(self.commands) // 2 - 1,
			middle_x - len(generated_str) // 2,
			generated_str, curses.color_pair(1) | curses.A_REVERSE
		)

		# Remembering whether we're into the plugins section
		in_plugins_section = False

		# Displays each command
		for i, (key_name, (function, name, hidden)) in enumerate(self.commands.items()):
			if key_name != self.command_symbol:
				generated_str = f"{self.command_symbol}{key_name} - {name}"
			else:
				generated_str = f"---- Plugin commands : ----"
				in_plugins_section = True

			self.stdscr.addstr(
				middle_y - len(self.commands) // 2 + i + in_plugins_section,
				middle_x - len(generated_str) // 2,
				generated_str, (curses.A_REVERSE if i % 2 == 0 else curses.A_NORMAL) \
					if key_name != self.command_symbol else curses.color_pair(1) | curses.A_REVERSE
			)
		self.stdscr.getch()
		self.stdscr.clear()


	def syntax_highlighting(self, line, splitted_line, i):
		"""
		Creates a syntax highlighting for the given line.
		:param line: The line to use for parsing.
		:param splitted_line: A split version of the line (split on spaces)
		:param i: The index of the line in the window.
		"""
		start_statement = splitted_line[0]
		if start_statement in tuple(sum(self.color_control_flow.values(), tuple())):
			if start_statement in self.color_control_flow["statement"]:
				c_pair = "statement"
			elif start_statement in self.color_control_flow["function"]:
				c_pair = "function"
			elif start_statement in self.color_control_flow["instruction"]:
				c_pair = "instruction"
			else:
				c_pair = "variable"
			# Overwrites the beginning of the line with the given color if possible
			self.stdscr.addstr(i, len(str(self.lines)) + 1, start_statement, curses.color_pair(self.color_pairs[c_pair]))

		# Finds all strings between quotes (single or double) and highlights them green
		quotes_indexes = tuple(i for i, ltr in enumerate(line) if ltr == "\"")
		for j, index in enumerate(quotes_indexes):
			if j % 2 == 0:
				try:
					self.stdscr.addstr(
						i,
						len(str(self.lines)) + 1 + index, line[index:quotes_indexes[j + 1] + 1],
						curses.color_pair(self.color_pairs["strings"] if not "=" in splitted_line[1] else 5)
					)
				except IndexError:
					if len(splitted_line) > 1:
						self.stdscr.addstr(
							i,
							len(str(self.lines)) + 1 + index, line[index:],
							curses.color_pair(self.color_pairs["strings"] if not "=" in splitted_line[1] else 5)
						)

		# Finds all equal signs to highlight them in statement color
		try:
			if "=" in splitted_line[1]:
				self.stdscr.addstr(
					i, len(str(self.lines)) + 2 + len(splitted_line[0]),
					splitted_line[1],
					curses.color_pair(self.color_pairs["statement"])
				)
		except IndexError:
			pass  # If there is no space in the line

		# Finds all '&' signs and gives them the statement color
		symbol_indexes = tuple(i for i, ltr in enumerate(line) if ltr == "&")
		for index in symbol_indexes:
			self.stdscr.addstr(
				i,
				len(str(self.lines)) + 1 + index, line[index],
				curses.color_pair(self.color_pairs["statement"])
			)

		# If the instruction is a function declaration, we highlight each types in the declaration
		if splitted_line[0] == "fx" and len(splitted_line) > 1:
			# Highlighting the function's return type; as statement if void or variable otherwise
			if splitted_line[1] in (*self.color_control_flow["variable"], "void"):
				self.stdscr.addstr(
					i, len(str(self.lines)) + 4,
					splitted_line[1],
					curses.color_pair(self.color_pairs["variable" if splitted_line[1] != "void" else "statement"])
				)

			# Highlighting each argument's type
			for j in range(3, len(splitted_line), 2):
				if splitted_line[j] in (*self.color_control_flow["variable"], "void"):
					self.stdscr.addstr(
						i, len(str(self.lines)) + 2 + len(" ".join(splitted_line[:j])),
						splitted_line[j], curses.color_pair(self.color_pairs["variable"])
					)

		# If the instruction is an array, we highlight the array's type and its size
		elif splitted_line[0] == "arr" and len(splitted_line) > 1:
			if splitted_line[1] in self.color_control_flow["variable"]:
				self.stdscr.addstr(
					i, len(str(self.lines)) + 5,
					splitted_line[1],
					curses.color_pair(self.color_pairs["variable"])
				)

			if len(splitted_line) > 3 and splitted_line[3].isdigit():
				self.stdscr.addstr(
					i, len(str(self.lines)) + len(" ".join(splitted_line[:3])) + 2,
					splitted_line[3],
					curses.color_pair(5)
				)


	def toggle_std_use(self):
		"""
		Toggles the use of the std namespace.in the C++ compilation.
		"""
		self.using_namespace_std = not self.using_namespace_std
		self.stdscr.addstr(self.rows - 1, 4, f"Toggled namespace std use to {self.using_namespace_std} ")


	def log(self, *args, **kwargs):
		"""
		Prints the given arguments if logs are enabled.
		"""
		if self.logs: print(*args, **kwargs)


	def save(self, text_to_save:str=None, quick_save:bool=False):
		"""
		Saves the code into a file or the clipboard, depending on what's chosen by the user.
		:param text_to_save: The text to save. If None, the contents of the editor. None by default.
		:param quick_save: Whether to quicksave (do the last save action). False by default.
		"""
		def save_to_clipboard():
			"""
			Saves the code to the clipboard.
			"""
			if remember_quicksave:
				self.last_save_action = "clipboard"
			pyperclip.copy(text_to_save)

		def save_to_file():
			"""
			Saves the code to a file.
			"""
			# Creates and displays a few messages to the user
			msg = (
				"Enter the absolute path to the file you want to",
				"save the code to, including the filename and extension.",
				f"Leave empty to cancel or type {self.command_symbol}v to paste the path from the clipboard",
				f"or type {self.command_symbol}b open the file browser."
			)
			for i in range(len(msg)):
				self.stdscr.addstr(self.rows // 2 + i, self.cols // 2 - len(msg[i]) // 2, msg[i])

			# Asks for the filename
			filename = input_text(self.stdscr, self.cols // 10, self.rows // 2 + len(msg))

			# If the filename is empty, we don't go inside the if statement (thus cancelling the save)
			if filename != "":
				# If the filename is equals to the command symbol + v (e.g. ':v'), we make it what is currently inside the clipboard
				if filename == self.command_symbol + "v":
					filename = pyperclip.paste()
				# If the filename is equals to the command symbol + b (e.g. ':b"), we open the file browser.
				if filename == self.command_symbol + "b":
					filename = browse_files(self.stdscr, can_create_files=True)()

				# If the path already exists, we ask the user to confirm the decision of overwriting the file
				if os.path.exists(filename):
					confirm = None
					def set_confirm(b:bool):
						"""
						Sets the value of confirm.
						"""
						nonlocal confirm
						confirm = b
					display_menu(self.stdscr, (
						("Yes", partial(set_confirm, True)),
						("No", partial(set_confirm, False))
					), label = "This file already exists. Do you want to overwrite it ?")
					# If the user didn't confirm, we don't save.
					if confirm is not True:
						return

				# If the filename is a valid path, we dump the code into the requested file
				with open(filename, "w", encoding="utf-8") as f:
					f.write(text_to_save)

				# Saving this save mode as quick action
				if remember_quicksave:
					self.last_save_action = filename

		remember_quicksave = text_to_save is None
		if text_to_save is None:
			text_to_save = self.current_text

		# If this is a regular save, we deploy the menu
		if quick_save is False:
			display_menu(
				self.stdscr,
				(
					("Save to clipboard", save_to_clipboard),
					("Save to file", save_to_file),
					("Cancel", lambda: None)
				), label = "-- SAVE --"
			)
			self.stdscr.clear()

		# If it is a quicksave :
		else:
			# We paste the code into the clipboard if the last save method was as so
			if self.last_save_action == "clipboard":
				save_to_clipboard()

			# Or we dump the code in the last file it was saved to
			else:
				with open(self.last_save_action, "w", encoding="utf-8") as f:
					f.write(text_to_save)

			self.stdscr.addstr(self.rows - 1, 4, f"Quicksaved to {self.last_save_action}")


	def open(self):
		"""
		Opens a code session.
		"""
		opened_code = False
		def open_from_clipboard():
			"""
			Saves the code to the clipboard.
			"""
			self.current_text = pyperclip.paste()
			nonlocal opened_code
			opened_code = True

		def open_from_file():
			"""
			Saves the code to a file.
			"""
			msg = (
				"Enter the absolute path to the file you want to",
				"open the code from, including the filename and extension.",
				f"Leave empty to cancel or type {self.command_symbol}v to paste the path from the clipboard.",
				f"or type {self.command_symbol}b to open the file browser."
			)
			for i in range(len(msg)):
				self.stdscr.addstr(self.rows // 2 + i, self.cols // 2 - len(msg[i]) // 2, msg[i])
			filename = input_text(self.stdscr, self.cols // 10, self.rows // 2 + len(msg))
			if filename != "":
				if filename == self.command_symbol + "v":
					filename = pyperclip.paste()
				if filename == self.command_symbol + "b":
					filename = browse_files(self.stdscr, can_create_files=False)()
				if os.path.exists(filename):
					with open(filename, "r", encoding="utf-8") as f:
						self.current_text = f.read()
						nonlocal opened_code
						opened_code = True
				else:
					msg = "This file doesn't seem to exist."
					self.stdscr.addstr(self.rows // 2, self.cols // 2 - len(msg), msg)

		display_menu(
			self.stdscr,
			(
				("Open from clipboard", open_from_clipboard),
				("Open from file", open_from_file),
				("Cancel", lambda: None)
			), label = "-- OPEN --"
		)

		self.stdscr.clear()
		if opened_code:
			self.current_index = 0
			self.stdscr.refresh()
			self.apply_stylings()


	def compile(self, noshow:bool=False) -> None | str:
		"""
		Compiles the inputted text into algorithmic code.
		:param noshow: Whether not to show the compiled code.
		"""
		self.instructions_list = self.current_text.split("\n")
		instructions_stack = []
		names = {"for": "Pour", "if": "Si", "while": "Tant Que", "switch": "Selon", "arr": "Tableau",
		         "case": "Cas", "default": "Autrement", "fx": "Fonction", "proc": "Procédure", "const": "Constante"}
		var_types = {"int": "Entier", "float": "Réel", "string": "Chaîne de caractères", "bool": "Booléen",
		             "char": "Caractère"}
		for i, line in enumerate(self.instructions_list):
			line = line.split(" ")
			instruction_name = line[0]
			instruction_params = line[1:]

			if instruction_name == "const":
				self.instructions_list[i] = f"{names['const']} : {var_types[instruction_params[0]]} : {' '.join(instruction_params[1:])}"

			elif instruction_name in var_types.keys():
				var_type = var_types[instruction_name]
				self.instructions_list[i] = ", ".join(instruction_params) + " : " + var_type + \
				                            ("s" if len(instruction_params) != 1 and instruction_name != "string" else "")

			elif instruction_name == "for":
				instructions_stack.append("for")
				self.instructions_list[i] = f"Pour {instruction_params[0]} allant de {instruction_params[1]} à " \
				                            f"{instruction_params[2]} avec un pas de " \
				                            f"{1 if len(instruction_params) < 4 else instruction_params[3]}"

			elif instruction_name == "end":
				last_elem = instructions_stack.pop()
				if last_elem != "vars":
					self.instructions_list[i] = f"Fin {names[last_elem]}"

			elif instruction_name == "while":
				instructions_stack.append("while")
				self.instructions_list[i] = f"Tant Que {' '.join(instruction_params)}"

			elif instruction_name == "if":
				instructions_stack.append("if")
				self.instructions_list[i] = f"Si {' '.join(instruction_params)}"

			elif instruction_name == "else":
				self.instructions_list[i] = f"Sinon"

			elif instruction_name == "elif":
				self.instructions_list[i] = f"Sinon Si {' '.join(instruction_params)}"

			elif instruction_name == "switch":
				instructions_stack.append("switch")
				self.instructions_list[i] = f"SELON {' '.join(instruction_params)}"

			elif instruction_name == "case":
				if "switch" not in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : 'case' statement outside of a 'switch'.")
					self.stdscr.getch()
					return None
				instructions_stack.append("case")
				self.instructions_list[i] = f"Cas {' '.join(instruction_params)}"

			elif instruction_name == "default":
				instructions_stack.append("default")
				self.instructions_list[i] = f"Autrement : {' '.join(instruction_params)}"

			elif instruction_name == "print":
				self.instructions_list[i] = f"Afficher({' '.join(instruction_params)})"

			elif instruction_name == "input":
				self.instructions_list[i] = f"Saisir({' '.join(instruction_params)})"

			elif instruction_name == "fx":
				while instruction_params[-1] == "": instruction_params.pop()
				if instruction_params[0] != "void":
					instructions_stack.append("fx")
					params = tuple(f"{instruction_params[i+1]} : {var_types[instruction_params[i]][instruction_params[i][0]=='&':]}" for i in range(2, len(instruction_params), 2))
					params = ", ".join(params)
					self.instructions_list[i] = f"Fonction {instruction_params[1]} ({params}) : {var_types[instruction_params[0]]}"
					del params
				else:
					instructions_stack.append("proc")
					params = tuple(f"{var_types[instruction_params[i]]} {instruction_params[i + 1][instruction_params[i+1][0]=='&':]}" for i in
					               range(2, len(instruction_params), 2))
					params = ", ".join(params)
					self.instructions_list[i] = f"Procédure {instruction_params[1]} ({params})"
					del params


			elif instruction_name == "precond": self.instructions_list[i] = f"Préconditions : {' '.join(instruction_params)}"
			elif instruction_name == "data": self.instructions_list[i] = f"Données : {' '.join(instruction_params)}"
			elif instruction_name == "datar": self.instructions_list[i] = f"Donnée/Résultat : {' '.join(instruction_params)}"
			elif instruction_name == "result": self.instructions_list[i] = f"Résultats : {' '.join(instruction_params)}"
			elif instruction_name == "desc": self.instructions_list[i] = f"Description : {' '.join(instruction_params)}"
			elif instruction_name == "return":
				# Checks we're not in a procedure
				if "proc" in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i+1} : 'return' statement in a procedure.")
					self.stdscr.getch()
					return None
				# Checks we're inside a function
				elif "fx" not in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i+1} : 'return' statement outside of a function.")
					self.stdscr.getch()
					return None
				else:
					self.instructions_list[i] = f"Retourner {' '.join(instruction_params)}"
			elif instruction_name == "fx_start":
				if instructions_stack[-1] == "vars": instructions_stack.pop()
				self.instructions_list[i] = f"Début : {' '.join(instruction_params)}"
			elif instruction_name == "vars":
				self.instructions_list[i] = f"Variables locales : {' '.join(instruction_params)}"
				instructions_stack.append("vars")

			elif instruction_name == "arr":  # Array : arr <type> <name> <size>
				try:
					self.instructions_list[i] = f"{instruction_params[1]} : tableau [ {instruction_params[2]} ] de type {var_types[instruction_params[0]].lower()}"
				except IndexError:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : 'arr' statement does not have all its parameters set")
					self.stdscr.getch()
					return None
				except KeyError:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : {instruction_params[0]} is not a recognized variable type")
					self.stdscr.getch()
					return None

			elif len(instruction_params) != 0:
				if instruction_params[0] == "=":
					self.instructions_list[i] = f"{instruction_name} ← {' '.join(instruction_params[1:])}"

				elif instruction_params[0].endswith("="):
					self.instructions_list[i] = f"{instruction_name} ← {instruction_name} {instruction_params[0][:-1]} {' '.join(instruction_params[1:])}"

			self.instructions_list[i] = self.instructions_list[i].replace("(ENDL)", "(FIN DE LIGNE)")
			self.instructions_list[i] = self.tab_char * (len(instructions_stack) - (1 if instruction_name in (*names.keys(), "else", "elif", "fx_start", "vars") else 0)) + self.instructions_list[i]

		final_compiled_code = "Début\n" + "".join(self.tab_char + instruction + "\n" for instruction in self.instructions_list) + "Fin"
		if noshow is False:
			self.stdscr.clear()
			try:
				self.stdscr.addstr(final_compiled_code)
				for plugin in self.plugins.values():
					if hasattr(plugin[1], "update_on_compilation"):
						plugin[1].update_on_compilation(final_compiled_code, "algo")
				self.stdscr.refresh()
				self.stdscr.getch()
			except curses.error: pass
			self.save(final_compiled_code)
			self.stdscr.clear()
			self.apply_stylings()
			self.stdscr.refresh()
		else:
			return final_compiled_code


	def compile_to_cpp(self):
		"""
		Compiles everything to C++ code ; might not always work.
		"""
		self.instructions_list = self.current_text.split("\n")
		instructions_stack = []
		names = ('for', 'if', 'while', 'switch', 'case', 'default', 'else', 'elif', 'const', 'arr')
		ifsanitize = lambda s: s.replace('ET', '&&').replace('OU', '||').replace('NON', '!')
		var_types = {"int": "int", "float": "float", "string": "std::string", "bool": "bool",
		             "char": "char"}
		fxtext = []
		last_elem = None

		for i, line in enumerate(self.instructions_list):
			line = line.split(" ")
			instruction_name = line[0]
			instruction_params = line[1:]


			if instruction_name == "const":
				self.instructions_list[i] = f"const {' '.join(instruction_params)}"

			elif instruction_name in var_types.keys():
				var_type = var_types[instruction_name]
				self.instructions_list[i] = var_type + " " + ", ".join(instruction_params)

			elif instruction_name == "for":
				instructions_stack.append("for")
				self.instructions_list[i] = f"for ({instruction_params[0]} = {instruction_params[1]}; " \
				                            f"{instruction_params[0]} <= {instruction_params[2]}; " \
				                            f"{instruction_params[0]} += {1 if len(instruction_params) < 4 else instruction_params[3]})" + "{"

			elif instruction_name == "end":
				last_elem = instructions_stack.pop()
				if last_elem in ("case", "default"):
					self.instructions_list[i] = self.tab_char + "break;"
				else:
					self.instructions_list[i] = "}"

			elif instruction_name == "while":
				instructions_stack.append("while")
				self.instructions_list[i] = f"while ({ifsanitize(' '.join(instruction_params))}) " + "{"

			elif instruction_name == "if":
				instructions_stack.append("if")
				self.instructions_list[i] = f"if ({ifsanitize(' '.join(instruction_params))}) " + "{"

			elif instruction_name == "else":
				self.instructions_list[i] = "} else {"

			elif instruction_name == "elif":
				self.instructions_list[i] = "} " + f"else if ({ifsanitize(' '.join(instruction_params))}) " + " {"

			elif instruction_name == "switch":
				instructions_stack.append("switch")
				self.instructions_list[i] = f"switch ({' '.join(instruction_params)}) " + "{"

			elif instruction_name == "case":
				if "switch" not in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : 'case' statement outside of a 'switch'.")
					self.stdscr.getch()
					return None
				instructions_stack.append("case")
				self.instructions_list[i] = f"case {' '.join(instruction_params)}:"

			elif instruction_name == "default":
				instructions_stack.append("default")
				self.instructions_list[i] = "default:"

			elif instruction_name == "print":
				self.instructions_list[i] = f"std::cout << {' '.join(instruction_params).replace(' & ', ' << ')}"

			elif instruction_name == "input":
				self.instructions_list[i] = f"std::cout << std::endl;\n{self.tab_char * ((len(instructions_stack) + ('fx' not in instructions_stack)))}std::cin >> {' '.join(instruction_params)}"

			elif instruction_name == "arr":  # Array : arr <type> <name> <size>
				try:
					self.instructions_list[i] = f"{instruction_params[0]}[{instruction_params[2]}] {instruction_params[1]};"
				except IndexError:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : 'arr' statement does not have all its parameters set")
					self.stdscr.getch()
					return None
				except KeyError:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : {instruction_params[0]} is not a recognized variable type")
					self.stdscr.getch()
					return None

			elif instruction_name == "fx":
				while instruction_params[-1] == "": instruction_params.pop()
				instructions_stack.append("fx")
				try:
					params = tuple(f"{var_types[instruction_params[i]]} {instruction_params[i+1]}" for i in range(2, len(instruction_params), 2))
					params = ", ".join(params)
					if instruction_params[0] != "void":
						self.instructions_list[i] = f"{var_types[instruction_params[0]]} {instruction_params[1]}({params}) " + "{"
					else:
						self.instructions_list[i] = f"void {instruction_params[1]}({params}) " + "{"
					del params
				except KeyError: pass

			elif instruction_name == "precond": self.instructions_list[i] = f"// Préconditions : {' '.join(instruction_params)}"
			elif instruction_name == "data": self.instructions_list[i] = f"// Données : {' '.join(instruction_params)}"
			elif instruction_name == "datar": self.instructions_list[i] = f"// Donnée/Résultat : {' '.join(instruction_params)}"
			elif instruction_name == "result": self.instructions_list[i] = f"// Résultats : {' '.join(instruction_params)}"
			elif instruction_name == "desc": self.instructions_list[i] = f"// Description : {' '.join(instruction_params)}"
			elif instruction_name == "vars": self.instructions_list[i] = f"// Variables locales : {' '.join(instruction_params)}"
			elif instruction_name == "fx_start": self.instructions_list[i] = ""
			elif instruction_name == "return":
				# Checks we're not in a procedure
				if "proc" in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i + 1} : 'return' statement in a procedure.")
					self.stdscr.getch()
					return None
				# Checks we're inside a function
				elif "fx" not in instructions_stack:
					self.stdscr.clear()
					self.stdscr.addstr(0, 0, f"Error on line {i+1} : 'return' statement outside of a function.")
					self.stdscr.getch()
					return None
				else:
					self.instructions_list[i] = f"return {' '.join(instruction_params)}"

			elif len(instruction_params) != 0:
				if instruction_params[0].endswith("="):
					self.instructions_list[i] = f"{instruction_name} {' '.join(instruction_params)}"

			self.instructions_list[i] = self.instructions_list[i].replace("puissance(", "pow(").replace("racine(", "sqrt(")
			self.instructions_list[i] = self.instructions_list[i].replace("aleatoire(", "rand(")
			self.instructions_list[i] = self.instructions_list[i].replace("(ENDL)", "\\n")
			self.instructions_list[i] = self.tab_char * (len(instructions_stack) - (1 if instruction_name in (*names, "fx") else 0))\
			                            + self.instructions_list[i] + (";" if instruction_name not in
			                                (*names, "end", "fx", "fx_start", "precond", "data", "datar", "result", "desc", "vars", "//") else "")
			if self.using_namespace_std:
				self.instructions_list[i] = self.instructions_list[i].replace("std::", "")

			if "fx" in instructions_stack or (instruction_name == "end" and last_elem == "fx"):
				fxtext.append(self.instructions_list[i])
				if instruction_name == "end":
					fxtext[-1] += "\n"
				self.instructions_list[i] = ""

		final_compiled_code = "#include <iostream>\n" + ("using namespace std;\n" if self.using_namespace_std else "") + \
		                      ("#include <math.h>\n" if 'puissance(' in self.current_text or \
		                                                'racine(' in self.current_text else '')  \
		                      + ("#include <stdlib.h>\n#include <time.h>\n" if 'aleatoire(' in self.current_text else '') + "\n" +\
							  "\n".join(fxtext) + "\n\nint main() {\n" + (self.tab_char + "srand(time(NULL));\n" if 'aleatoire(' in self.current_text else '') \
							  + "".join(
			self.tab_char + instruction + "\n" for instruction in self.instructions_list if instruction != ";" and instruction != "")\
		                      + self.tab_char + "return 0;\n}"

		self.stdscr.clear()
		self.stdscr.refresh()
		try:
			self.stdscr.addstr(final_compiled_code)
		except curses.error: pass
		for plugin in self.plugins.values():
			if hasattr(plugin[1], "update_on_compilation"):
				plugin[1].update_on_compilation(final_compiled_code, "cpp")
		self.stdscr.getch()
		self.save(final_compiled_code)
		self.stdscr.clear()
		self.apply_stylings()
		self.stdscr.refresh()



def generate_crash_file(app:App, *args):
	"""
	Generates a .crash file.
	:param app: The application instance.
	"""
	with open(".crash", "w", encoding="utf-8") as f:
		f.write(app.current_text)

if __name__ == "__main__":
	# Selects the current working directory as the directory of this file
	os.chdir(os.path.dirname(__file__))

	try:
		# Instanciates the app
		app = App(
			command_symbol=":" if "-command_symbol" not in sys.argv else sys.argv[sys.argv.index("--command_symbol") + 1],
			using_namespace_std=False if "--using_namespace_std" not in sys.argv else sys.argv[sys.argv.index("--using_namespace_std") + 1],
			logs="--nologs" not in sys.argv
		)

		# If a file was specified as argument
		if "--file" in sys.argv:
			filename = sys.argv[sys.argv.index("--file") + 1]
			# We read the file contents and store it as the app's current text
			with open(filename, "r", encoding="utf-8") as f:
				app.current_text = f.read()
			# We make it so the quicksave will automatically save to this file
			app.last_save_action = filename

		# Detects console closing and creates a .crash file, depending on the OS
		import platform
		if platform.system() == "Windows":
			import win32api
			win32api.SetConsoleCtrlHandler(partial(generate_crash_file, app), True)
		else:
			import signal
			signal.signal(signal.SIGHUP, partial(generate_crash_file, app))

		# Wr launch the app
		curses.wrapper(app.main)

	# If a crash occurs, generates a .crash file
	except Exception as e:
		# In the event of a crash, saves the current_text to a .crash file
		generate_crash_file(app)
		# Then raises the exception again
		raise e
