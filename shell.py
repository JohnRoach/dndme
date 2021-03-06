from attr import attrs, attrib
from dice import roll_dice, roll_dice_expr
from initiative import TurnManager
from math import inf
from models import Character, Encounter, Monster
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.contrib.completers import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import style_from_dict
from prompt_toolkit.token import Token
import glob
import pytoml as toml
import sys


commands = {}
manager = KeyBindingManager.for_prompt()
history = InMemoryHistory()
command_completer = None
style = style_from_dict({
    Token.Toolbar: '#ffffff bg:#333333',
})


class DnDCompleter(Completer):
    """
    Simple autocompletion on a list of words.

    :param base_commands: List of base commands.
    :param ignore_case: If True, case-insensitive completion.
    :param meta_dict: Optional dict mapping words to their meta-information.
    :param WORD: When True, use WORD characters.
    :param sentence: When True, don't complete by comparing the word before the
        cursor, but by comparing all the text before the cursor. In this case,
        the list of words is just a list of strings, where each string can
        contain spaces. (Can not be used together with the WORD option.)
    :param match_middle: When True, match not only the start, but also in the
                         middle of the word.
    """
    def __init__(self, base_commands, ignore_case=False, meta_dict=None,
                 WORD=False, sentence=False, match_middle=False):
        assert not (WORD and sentence)

        self.base_commands = sorted(list(base_commands))
        self.ignore_case = ignore_case
        self.meta_dict = meta_dict or {}
        self.WORD = WORD
        self.sentence = sentence
        self.match_middle = match_middle

    def get_completions(self, document, complete_event):
        # Get word/text before cursor.
        if self.sentence:
            word_before_cursor = document.text_before_cursor
        else:
            word_before_cursor = document.get_word_before_cursor(
                    WORD=self.WORD)

        if self.ignore_case:
            word_before_cursor = word_before_cursor.lower()

        def word_matcher(word):
            """ True when the command before the cursor matches. """
            if self.ignore_case:
                word = word.lower()

            if self.match_middle:
                return word_before_cursor in word
            else:
                return word.startswith(word_before_cursor)

        suggestions = []
        document_text_list = document.text.split(' ')

        if len(document_text_list) < 2:
            suggestions = self.base_commands

        elif document_text_list[0] in self.base_commands:
            command = commands[document_text_list[0]]
            suggestions = command.get_suggestions(document_text_list) or []

        for word in suggestions:
            if word_matcher(word):
                display_meta = self.meta_dict.get(word, '')
                yield Completion(word, -len(word_before_cursor),
                                    display_meta=display_meta)


@attrs
class GameState:
    characters = attrib(default={})
    monsters = attrib(default={})
    encounter = attrib(default=None)
    tm = attrib(default=None)

    @property
    def combatant_names(self):
        return sorted(list(self.characters.keys()) +
                list(self.monsters.keys()))

    def get_target(self, name):
        return self.characters.get(name) or self.monsters.get(name)


class Command:

    keywords = ['command']

    def __init__(self, game):
        self.game = game
        for kw in self.keywords:
            commands[kw] = self
        print("Registered "+self.__class__.__name__)

    def get_suggestions(self, words):
        return []

    def do_command(self, *args):
        print("Nothing happens.")

    def show_help_text(self, keyword):
        if hasattr(self, 'help_text'):
            divider = "-" * len(keyword)
            print(self.help_text.format(**locals()))
        else:
            print(f"No help text available for: {keyword}")


class ListCommands(Command):

    keywords = ['commands']
    help_text = """{keyword}
{divider}
Summary: List available commands

Usage: {keyword}
"""

    def do_command(self, *args):
        print("Available commands:\n")
        for keyword in list(sorted(commands.keys())):
            print('*', keyword)
        print()


class Help(Command):

    keywords = ['help']
    help_text = """{keyword}
{divider}
Summary: Get help for a command.

Usage: {keyword} <command>
"""

    def get_suggestions(self, words):
        return list(sorted(commands.keys()))

    def do_command(self, *args):
        if not args:
            self.show_help_text('help')
            return

        keyword = args[0]
        command = commands.get(keyword)
        if not command:
            print(f"Unknown command: {keyword}")
            return
        command.show_help_text(keyword)

    def show_help_text(self, keyword):
        super().show_help_text(keyword)
        ListCommands.do_command(self, *[])


class Quit(Command):

    keywords = ['quit', 'exit']
    help_text = """{keyword}
{divider}
Summary: quit the shell

Usage: {keyword}
"""

    @manager.registry.add_binding(Keys.ControlD)
    def do_command(self, *args):
        print("Goodbye!")
        sys.exit(1)


class Roll(Command):

    keywords = ['roll', 'dice']
    help_text = """{keyword}
{divider}
Summary: Roll dice using a dice expression

Usage: {keyword} <dice expression> [<dice expression> ...]

Examples:

    {keyword} 3d6
    {keyword} 1d20+2
    {keyword} 2d4-1
    {keyword} 1d20 1d20
"""

    def do_command(self, *args):
        results = []
        for dice_expr in args:
            try:
                results.append(str(roll_dice_expr(dice_expr)))
            except ValueError:
                print(f"Invalid dice expression: {dice_expr}")
                return
        print(', '.join(results))


class Load(Command):

    keywords = ['load']
    help_text = """{keyword}
{divider}
Summary: Load stuff

Usage:
    {keyword} party
    {keyword} encounter
"""

    def get_suggestions(self, words):
        if len(words) == 2:
            return ['encounter', 'party']

    def do_command(self, *args):
        if not args:
            print("Load what?")
            return
        if args[0] == 'party':
            self.load_party()
        elif args[0] == 'encounter':
            self.load_encounter()

    def load_party(self):
        party = {}
        with open('party.toml', 'r') as fin:
            party = toml.load(fin)
        self.game.characters = \
                {x['name']: Character(**x) for x in party.values()}
        print("OK; loaded {} characters".format(len(party)))

    def load_encounter(self):
        available_encounter_files = glob.glob('encounters/*.toml')
        if not available_encounter_files:
            print("No available encounters found.")
            return
        print("Available encounters:\n")
        encounters = []
        for i, filename in enumerate(available_encounter_files, 1):
            encounter = Encounter(**toml.load(open(filename, 'r')))
            encounters.append(encounter)
            print(f"{i}: {encounter.name} ({encounter.location})")
        pick = input("\nLoad encounter: ")
        if not pick.isdigit():
            print("Invalid encounter.")
            return
        pick = int(pick) - 1
        if pick < 0 or pick > len(encounters):
            print("Invalid encounter.")
            return
        self.game.encounter = encounter = encounters[pick]
        print(f"Loaded encounter: {encounter.name}")

        for group in encounter.groups.values():
            available_monster_files = glob.glob('monsters/*.toml')
            monsters = []

            for filename in available_monster_files:
                monster = toml.load(open(filename, 'r'))
                if monster['name'] == group['monster']:
                    for i in range(group['count']):
                        monsters.append(Monster(**monster))
                    break

            for i in range(len(monsters)):
                if 'max_hp' in group and len(group['max_hp']) == len(monsters):
                    monsters[i].max_hp = group['max_hp'][i]
                    monsters[i].cur_hp = group['max_hp'][i]
                else:
                    monsters[i].max_hp = monsters[i]._max_hp
                    monsters[i].cur_hp = monsters[i].max_hp

                if monsters[i].name[0].islower():
                    monsters[i].name = monsters[i].name+str(i+1)
                self.game.monsters[monsters[i].name] = monsters[i]


class Show(Command):

    keywords = ['show']

    def get_suggestions(self, words):
        if len(words) == 2:
            return ['monsters', 'party', 'turn']

    def do_command(self, *args):
        if not args:
            print("Show what?")
            return
        if args[0] == 'party':
            self.show_party()
        elif args[0] == 'monsters':
            self.show_monsters()
        elif args[0] == 'turn':
            self.show_turn()

    def show_party(self):
        party = list(sorted(self.game.characters.items()))
        for name, character in party:
            print(f"{name:20}\tHP: {character.cur_hp}/{character.max_hp}"
                    f"\tAC: {character.ac}\tPer: {character.perception}"
            )
            if character.conditions:
                conds = ', '.join([f"{x}:{y}"
                        if y != inf else x
                        for x, y in character.conditions.items()])
                print(f"    Conditions: {conds}")

    def show_monsters(self):
        monsters = list(sorted(self.game.monsters.items()))
        for name, monster in monsters:
            print(f"{name:20}\tHP: {monster.cur_hp}/{monster.max_hp}"
                    f"\tAC: {monster.ac}\tPer: {monster.perception}"
            )
            if monster.conditions:
                conds = ', '.join([f"{x}:{y}"
                        if y != inf else x
                        for x, y in monster.conditions.items()])
                print(f"    Conditions: {conds}")

    def show_turn(self):
        if not self.game.tm:
            print("No turn in progress.")
            return
        elif not self.game.tm.cur_turn:
            print("No turn in progress.")
            return
        turn = self.game.tm.cur_turn
        print(f"Round: {turn[0]} Initiative: {turn[1]} Name: {turn[2].name}")


class Start(Command):

    keywords = ['start']

    def do_command(self, *args):
        self.game.tm = TurnManager()

        for monster in self.game.monsters.values():
            self.game.tm.add_combatant(monster, roll_dice(1, 20,
                modifier=monster.initiative_mod))

        for character in self.game.characters.values():
            roll = input(f"Initiative for {character.name}: ")
            if not roll:
                roll = roll_dice(1, 20, modifier=character.initiative_mod)
            elif roll.isdigit():
                roll = int(roll)
            self.game.tm.add_combatant(character, roll)

        print("\nBeginning combat with: ")
        for roll, combatants in self.game.tm.turn_order:
            for combatant in combatants:
                print(f"{roll}: {combatant.name}")

        self.game.tm.turns = self.game.tm.generate_turns()


class NextTurn(Command):

    keywords = ['next']

    @manager.registry.add_binding(Keys.ControlN)
    def do_command(self, *args):
        if not game.tm:
            if not hasattr(self, "game"):
            # this feels very hacky however it looks like key binding
            # takes over object. To me it looks like we might want to change
            # approach on how we load commands.
                print("")
            print("Combat hasn't started yet.")
            main_loop(game)
            return

        turn = game.tm.cur_turn
        if turn:
            combatant = turn[-1]
            conditions_removed = combatant.decrement_condition_durations()
            if conditions_removed:
                print(f"{combatant.name} conditions removed: "
                        f"{', '.join(conditions_removed)}")

        turn = next(game.tm.turns)
        game.tm.cur_turn = turn
        Show.show_turn(self)


class Damage(Command):

    keywords = ['damage', 'hurt']

    def get_suggestions(self, words):
        if len(words) == 2:
            return self.game.combatant_names

    def do_command(self, *args):
        target_name = args[0]
        amount = int(args[1])

        target = self.game.get_target(target_name)
        if not target:
            print(f"Invalid target: {target_name}")
            return

        target.cur_hp -= amount
        print(f"Okay; damaged {target_name}.")


class Heal(Command):

    keywords = ['heal']

    def get_suggestions(self, words):
        if len(words) == 2:
            return self.game.combatant_names

    def do_command(self, *args):
        target_name = args[0]
        amount = int(args[1])

        target = self.game.get_target(target_name)
        if not target:
            print(f"Invalid target: {target_name}")
            return

        target.cur_hp += amount
        print(f"Okay; healed {target_name}.")


class Swap(Command):

    keywords = ['swap']
    help_text = """{keyword}
{divider}
Summary: Swap two combatants in turn order.

Usage: {keyword} <combatant1> <combatant2>
"""

    def get_suggestions(self, words):
        if len(words) in (2, 3):
            return self.game.combatant_names

    def do_command(self, *args):
        name1 = args[0]
        name2 = args[1]

        combatant1 = self.game.characters.get(name1) or \
                self.game.monsters.get(name1)
        combatant2 = self.game.characters.get(name2) or \
                self.game.monsters.get(name2)

        if not combatant1:
            print(f"Invalid target: {name1}")
            return

        if not combatant2:
            print(f"Invalid target: {name2}")
            return

        self.game.tm.swap(combatant1, combatant2)
        print(f"Okay; swapped {name1} and {name2}.")


class Move(Command):

    keywords = ['move']
    help_text = """{keyword}
{divider}
Summary: Move a combatant to a different initiative value.

Usage: {keyword} <combatant> <initiative>
"""

    def get_suggestions(self, words):
        if len(words) == 2:
            return self.game.combatant_names

    def do_command(self, *args):
        name = args[0]

        target = self.game.get_target(name)

        if not target:
            print(f"Invalid target: {name}")
            return

        try:
            new_initiative = int(args[1])
        except ValueError:
            print("Invalid initiative value")
            return

        self.game.tm.move(target, new_initiative)
        print(f"Okay; moved {name} to {new_initiative}.")


class SetCondition(Command):

    keywords = ['set']
    help_text = """{keyword}
{divider}
Summary: Set a condition on a target, optionally for a duration

Usage: {keyword} <target> <condition> [<duration> [<units>]]

Examples:

    {keyword} Frodo prone
    {keyword} Aragorn smolder 3
    {keyword} Gandalf concentrating 1 minute
    {keyword} Gollum lucid 5 minutes
"""
    conditions = [
        'blinded',
        'charmed',
        'concentrating',
        'deafened',
        'dead',
        'exhausted',
        'frightened',
        'grappled',
        'incapacitated',
        'invisible',
        'paralyzed',
        'petrified',
        'poisoned',
        'prone',
        'restrained',
        'stunned',
        'unconscious',
    ]

    def get_suggestions(self, words):
        if len(words) == 2:
            return self.game.combatant_names
        elif len(words) == 3:
            return self.conditions

    def do_command(self, *args):
        target_name = args[0]
        condition = args[1]
        duration = inf
        if len(args) >= 3:
            duration = int(args[2])
        if len(args) >= 4:
            units = args[3]
            multipliers = {
                'turn': 1,
                'turns': 1,
                'round': 1,
                'rounds': 1,
                'minute': 10,
                'minutes': 10,
                'min': 10,
            }
            duration *= multipliers.get(units, 1)

        target = self.game.get_target(target_name)
        if not target:
            print(f"Invalid target: {target_name}")
            return

        target.set_condition(condition, duration=duration)
        print(f"Okay; set condition '{condition}' on {target_name}.")


class UnsetCondition(Command):

    keywords = ['unset']
    help_text = """{keyword}
{divider}
Summary: Remove a condition from a target

Usage: {keyword} <target> <condition>

Examples:

    {keyword} Frodo prone
"""

    def get_suggestions(self, words):
        if len(words) == 2:
            return self.game.combatant_names
        elif len(words) == 3:
            target_name = words[1]
            target = self.game.get_target(target_name)
            if not target:
                return []
            return list(sorted(target.conditions.keys()))

    def do_command(self, *args):
        target_name = args[0]
        condition = args[1]

        target = self.game.get_target(target_name)
        if not target:
            print(f"Invalid target: {target_name}")
            return

        target.unset_condition(condition)
        print(f"Okay; removed condition '{condition}' from {target_name}.")


def register_commands(game):
    ListCommands(game)
    Help(game)
    Quit(game)
    Load(game)
    Show(game)
    Start(game)
    NextTurn(game)
    Damage(game)
    Heal(game)
    Swap(game)
    Move(game)
    Roll(game)
    SetCondition(game)
    UnsetCondition(game)


def get_bottom_toolbar_tokens(cli):
    return [(Token.Toolbar, 'Next:Ctrl+N   Exit:Ctrl+D ')]


def main_loop(game):
    while True:
        try:
            user_input = prompt("> ",
                completer=DnDCompleter(base_commands=commands.keys(),
                        ignore_case=True),
                history=history,
                get_bottom_toolbar_tokens=get_bottom_toolbar_tokens,
                key_bindings_registry=manager.registry,
                style=style).split()
            if not user_input:
                continue

            command = commands.get(user_input[0]) or None
            if not command:
                print("Unknown command.")
                continue

            command.do_command(*user_input[1:])
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == '__main__':
    game = GameState()
    register_commands(game)
    main_loop(game)
