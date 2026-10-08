#!/usr/bin/env python3
"""
Lumenfall: a tiny open-world, choice-driven story in one Python file.
- Text-based exploration with a small but expandable world grid
- Inventory, items, simple combat, and quests
- Faction reputation and multiple endings based on choices
- Save/Load to JSON (slots 1-3)

Run: python lumenfall.py
"""
from __future__ import annotations
import json
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

# -------------------------------
# Data Models
# -------------------------------

@dataclass
class Item:
    id: str
    name: str
    desc: str
    usable: bool = False
    heal: int = 0
    attack: int = 0

@dataclass
class NPC:
    id: str
    name: str
    role: str
    dialog: List[str] = field(default_factory=list)
    choices: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    # choices: key -> (effect_key, next_dialog_id)
    # effect_key examples: "REP:Watch:+2", "QUEST:add:lost_blade", "ITEM:add:medkit"
    hostile: bool = False
    hp: int = 10
    attack: int = 2

@dataclass
class Tile:
    name: str
    desc: str
    exits: Dict[str, Tuple[int,int]] = field(default_factory=dict)
    items: List[str] = field(default_factory=list)  # item ids present
    npcs: List[str] = field(default_factory=list)   # npc ids present
    safe_rest: bool = False

@dataclass
class Player:
    name: str = "Wanderer"
    hp: int = 20
    max_hp: int = 20
    attack: int = 3
    inventory: List[str] = field(default_factory=list)  # item ids
    pos: Tuple[int,int] = (0,0)
    quests: Dict[str, str] = field(default_factory=dict)  # quest_id -> status
    rep: Dict[str, int] = field(default_factory=lambda: {"Watch":0, "Guild":0, "Syndicate":0})

    def is_alive(self) -> bool:
        return self.hp > 0

# -------------------------------
# World Definition
# -------------------------------

ITEMS: Dict[str, Item] = {
    "medkit": Item("medkit", "Medkit", "A basic medical kit.", usable=True, heal=8),
    "blade": Item("blade", "Guild-Forge Blade", "A well-balanced short blade.", attack=2),
    "pistol": Item("pistol", "Rusty Pistol", "Seen better days but still fires.", attack=3),
    "keywatch": Item("keywatch", "Watch Key", "Opens a locker at the Watch Barracks."),
    "lockpick": Item("lockpick", "Lockpicks", "Useful for quiet doors (Syndicate likes this)."),
    "rations": Item("rations", "Rations", "Dried food, keeps you going.", usable=True, heal=4),
}

NPCS: Dict[str, NPC] = {
    "watch_captain": NPC(
        id="watch_captain",
        name="Captain Merrin",
        role="Watch",
        dialog=[
            "Halt. Lumenfall's safer than it looks—if folk make the right choices.",
            "Rumors say the Syndicate stirs trouble in the Old Docks.",
            "Earn the Watch's trust and you'll earn the city a future.",
        ],
        choices={
            "Swear to aid the Watch": ("REP:Watch:+2;QUEST:add:old_docks", "watch2"),
            "Ask about supplies": ("ITEM:add:keywatch", "watch3"),
            "Insult authority": ("REP:Watch:-2", "watch4"),
        },
    ),
    "guild_smith": NPC(
        id="guild_smith",
        name="Master Anka",
        role="Guild",
        dialog=[
            "Steel sings when wielded for right causes.",
            "Bring scrap from the Outskirts and I'll shape you a blade.",
        ],
        choices={
            "Request a forged blade": ("ITEM:add:blade;REP:Guild:+1", "guild2"),
            "Offer protection to the Guild": ("REP:Guild:+2;QUEST:add:lost_blade", "guild3"),
        },
    ),
    "syndicate_visor": NPC(
        id="syndicate_visor",
        name="Visor Nyx",
        role="Syndicate",
        dialog=[
            "We don't break rules; we write the ones people follow.",
            "Quiet hands earn loud rewards.",
        ],
        choices={
            "Take a covert job": ("REP:Syndicate:+2;QUEST:add:quiet_job;ITEM:add:lockpick", "syn2"),
            "Threaten the Syndicate": ("REP:Syndicate:-2", "syn3"),
        },
    ),
    "dock_thug": NPC(
        id="dock_thug",
        name="Dockside Bruiser",
        role="Syndicate",
        hostile=True,
        hp=12,
        attack=3,
    ),
}

WORLD: Dict[Tuple[int,int], Tile] = {
    (0,0): Tile(
        name="City Gate",
        desc="The weathered gate of Lumenfall. Lanterns flicker as dusk gathers.",
        items=["rations"],
        safe_rest=True,
    ),
    (0,1): Tile(
        name="Watch Barracks",
        desc="Spartan halls and a scent of oil. A wall map tracks trouble spots.",
        npcs=["watch_captain"],
        safe_rest=True,
    ),
    (1,0): Tile(
        name="Guild Forge",
        desc="Sparks leap from anvils. The Guild shapes more than steel here.",
        npcs=["guild_smith"],
    ),
    (-1,0): Tile(
        name="Old Docks",
        desc="Creaking planks, black water. Shadows trade whispers.",
        npcs=["syndicate_visor", "dock_thug"],
    ),
    (1,1): Tile(
        name="Market Square",
        desc="Merchants hawk wares; laughter masks worry.",
    ),
}

# connect exits
for (x,y), tile in WORLD.items():
    exits = {}
    for dx, dy, dname in [(0,1,"north"),(0,-1,"south"),(1,0,"east"),(-1,0,"west")]:
        p = (x+dx, y+dy)
        if p in WORLD:
            exits[dname] = p
    tile.exits = exits

# -------------------------------
# Utilities
# -------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

SAVE_DIR = os.path.join(os.path.dirname(__file__), "saves")

def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)

# -------------------------------
# Game Systems
# -------------------------------

class Game:
    def __init__(self):
        self.player = Player()
        self.turn = 0
        random.seed()

    # ---------- I/O ----------
    def say(self, text: str):
        print(text)

    def header(self, text: str):
        print("\n== " + text + " ==")

    # ---------- Save/Load ----------
    def save(self, slot: int = 1):
        ensure_save_dir()
        data = {
            "player": asdict(self.player),
            "turn": self.turn,
            "world_items": {str(k): v.items for k,v in WORLD.items()},
            "world_npcs": {str(k): v.npcs for k,v in WORLD.items()},
        }
        path = os.path.join(SAVE_DIR, f"slot{slot}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.say(f"Saved to slot {slot}.")

    def load(self, slot: int = 1):
        path = os.path.join(SAVE_DIR, f"slot{slot}.json")
        if not os.path.exists(path):
            self.say("No save in that slot.")
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.player = Player(**data["player"])  # type: ignore
        # restore world pickup state
        for k, items in data.get("world_items", {}).items():
            k_tuple = tuple(int(x) for x in k.strip("() ").split(","))  # type: ignore
            WORLD[k_tuple].items = items
        for k, npcs in data.get("world_npcs", {}).items():
            k_tuple = tuple(int(x) for x in k.strip("() ").split(","))  # type: ignore
            WORLD[k_tuple].npcs = npcs
        self.turn = data.get("turn", 0)
        self.look()
        self.say(f"Loaded slot {slot}.")

    # ---------- World ----------
    def tile(self) -> Tile:
        return WORLD[self.player.pos]

    def look(self):
        t = self.tile()
        self.header(t.name)
        self.say(t.desc)
        if t.items:
            self.say("Items here: " + ", ".join(ITEMS[i].name for i in t.items))
        if t.npcs:
            self.say("People here: " + ", ".join(NPCS[n].name for n in t.npcs))
        if t.exits:
            self.say("Exits: " + ", ".join(f"{d}" for d in t.exits.keys()))

    def move(self, direction: str):
        t = self.tile()
        if direction not in t.exits:
            self.say("You can't go that way.")
            return
        self.player.pos = t.exits[direction]
        self.turn += 1
        self.look()
        self.random_event()

    def random_event(self):
        # small chance for ambient flavor or find rations
        if random.random() < 0.15:
            flavor = random.choice([
                "A bell tolls in the distance.",
                "You catch a whisper: 'The night favors the bold.'",
                "A street performer flips a coin that never seems to land.",
            ])
            self.say(flavor)
        if random.random() < 0.10:
            self.say("You find a packet of rations.")
            self.player.inventory.append("rations")

    # ---------- Inventory ----------
    def take(self, item_name: str):
        t = self.tile()
        for iid in list(t.items):
            it = ITEMS[iid]
            if item_name.lower() in [it.name.lower(), it.id.lower()]:
                t.items.remove(iid)
                self.player.inventory.append(iid)
                self.say(f"You take {it.name}.")
                return
        self.say("No such item here.")

    def use(self, item_name: str):
        for iid in list(self.player.inventory):
            it = ITEMS[iid]
            if item_name.lower() in [it.name.lower(), it.id.lower()]:
                if it.usable:
                    self.player.hp = clamp(self.player.hp + it.heal, 0, self.player.max_hp)
                    self.player.inventory.remove(iid)
                    self.say(f"You use {it.name}. HP: {self.player.hp}/{self.player.max_hp}")
                else:
                    self.say(f"You can't use {it.name} right now.")
                return
        self.say("You don't have that.")

    # ---------- NPC / Dialog ----------
    def talk(self, who: str):
        t = self.tile()
        # find target by id or name
        target_id = None
        for nid in t.npcs:
            n = NPCS[nid]
            if who.lower() in [n.id.lower(), n.name.lower().split()[0].lower()]:
                target_id = nid
                break
        if not target_id:
            self.say("No one here by that name.")
            return
        npc = NPCS[target_id]
        if npc.hostile:
            self.say(f"{npc.name} snarls—no words, only fists.")
            self.combat(target_id)
            return
        # show dialog
        self.header(npc.name)
        for line in npc.dialog:
            self.say(f"\"{line}\"")
        if npc.choices:
            self.say("Choices:")
            opts = list(npc.choices.items())
            for i, (txt, _) in enumerate(opts, 1):
                self.say(f"  {i}. {txt}")
            sel = input("> Pick (number) or Enter to leave: ").strip()
            if sel.isdigit():
                idx = int(sel)-1
                if 0 <= idx < len(opts):
                    txt, (effect, _next) = opts[idx]
                    self.apply_effects(effect)
                    self.say(f"You chose: {txt}")
        else:
            self.say("They have nothing else to say.")

    def apply_effects(self, effect_str: str):
        # effect parts separated by ';'
        for part in effect_str.split(';'):
            part = part.strip()
            if not part:
                continue
            if part.startswith("REP:"):
                # REP:Faction:+2
                _, faction, delta = part.split(':')
                self.player.rep[faction] = self.player.rep.get(faction,0) + int(delta)
                self.say(f"Reputation with {faction}: {self.player.rep[faction]}")
            elif part.startswith("QUEST:add:"):
                qid = part.split(':',2)[2]
                if qid not in self.player.quests:
                    self.player.quests[qid] = "active"
                    self.say(f"Quest started: {qid.replace('_',' ').title()}")
            elif part.startswith("QUEST:complete:"):
                qid = part.split(':',2)[2]
                if self.player.quests.get(qid) == "active":
                    self.player.quests[qid] = "completed"
                    self.say(f"Quest completed: {qid.replace('_',' ').title()}")
            elif part.startswith("ITEM:add:"):
                iid = part.split(':',2)[2]
                self.player.inventory.append(iid)
                self.say(f"Received: {ITEMS[iid].name}")

    # ---------- Combat ----------
    def combat(self, npc_id: str):
        npc = NPCS[npc_id]
        self.header(f"Combat: {npc.name}")
        # compute weapon bonus
        atk_bonus = 0
        for iid in self.player.inventory:
            atk_bonus = max(atk_bonus, ITEMS[iid].attack)
        while npc.hp > 0 and self.player.is_alive():
            self.say(f"Your HP {self.player.hp}/{self.player.max_hp} | {npc.name} HP {npc.hp}")
            cmd = input("> (attack/use [item]/run): ").strip().lower()
            if cmd.startswith("use "):
                self.use(cmd[4:])
                continue
            elif cmd == "run":
                if random.random() < 0.5:
                    self.say("You slip away into the shadows!")
                    return
                else:
                    self.say("You fail to escape!")
            # attack
            dmg = self.player.attack + random.randint(0,2) + atk_bonus
            npc.hp = max(0, npc.hp - dmg)
            self.say(f"You strike for {dmg}!")
            if npc.hp <= 0:
                self.say(f"{npc.name} falls.")
                # quest or rep outcomes
                if npc.role == "Syndicate":
                    self.player.rep["Syndicate"] -= 1
                self.apply_effects("QUEST:complete:old_docks")
                # remove npc from tile
                if npc_id in self.tile().npcs:
                    self.tile().npcs.remove(npc_id)
                break
            # enemy turn
            edmg = npc.attack + random.randint(0,2)
            self.player.hp = max(0, self.player.hp - edmg)
            self.say(f"{npc.name} hits for {edmg}!")
        if not self.player.is_alive():
            self.game_over()

    def rest(self):
        if self.tile().safe_rest:
            heal = random.randint(4,8)
            self.player.hp = clamp(self.player.hp + heal, 0, self.player.max_hp)
            self.say(f"You rest safely and recover {heal} HP. ({self.player.hp}/{self.player.max_hp})")
        else:
            self.say("This place is too risky to rest.")

    # ---------- Endings ----------
    def check_endings(self) -> Optional[str]:
        # If any faction rep >= 5 -> faction ending
        for faction, val in self.player.rep.items():
            if val >= 5:
                return f"ENDING: {faction} Triumph — Your deeds secure {faction}'s vision for Lumenfall."
        # If completed certain quests in combination
        if self.player.quests.get("old_docks") == "completed" and self.player.rep.get("Watch",0) >= 3:
            return "ENDING: Dawn Watch — The docks are pacified and the Watch strengthens rule of law."
        if self.player.quests.get("quiet_job") == "completed" and self.player.rep.get("Syndicate",0) >= 3:
            return "ENDING: Shadow Accord — The Syndicate ushers in an age of controlled chaos."
        if self.player.quests.get("lost_blade") == "completed" and self.player.rep.get("Guild",0) >= 3:
            return "ENDING: Forged Future — The Guild's craft rebuilds the city's hope."
        return None

    def game_over(self):
        self.header("You have fallen")
        self.say("The city remembers the brave—and the foolish.")
        exit(0)

    # ---------- UI ----------
    def show_help(self):
        self.say(
            """
Commands:
  look                        — describe current area
  go [north/east/south/west]  — move
  talk [name/id]              — talk or engage
  take [item]                 — pick up an item
  use [item]                  — use a consumable (e.g., medkit)
  inv                         — show inventory
  stats                       — show hp, attack, reputation
  quests                      — list quests
  rest                        — rest if it's safe
  save [1-3]                  — save to slot
  load [1-3]                  — load from slot
  help                        — show this help
  end                         — check if an ending is available now
  quit                        — exit the game
            """.strip()
        )

    def show_inventory(self):
        if not self.player.inventory:
            self.say("Inventory empty.")
            return
        self.say("Inventory:")
        for iid in self.player.inventory:
            it = ITEMS[iid]
            self.say(f"- {it.name}: {it.desc}")

    def show_stats(self):
        p = self.player
        self.say(f"HP {p.hp}/{p.max_hp}, ATK {p.attack}")
        self.say("Reputation: " + ", ".join(f"{k} {v}" for k,v in p.rep.items()))

    def show_quests(self):
        if not self.player.quests:
            self.say("No active quests.")
            return
        for q, st in self.player.quests.items():
            self.say(f"- {q.replace('_',' ').title()}: {st}")

    # ---------- Locker interaction (example of item-gated) ----------
    def open_locker(self):
        if self.tile().name != "Watch Barracks":
            self.say("No locker here.")
            return
        if "keywatch" in self.player.inventory:
            self.say("You open a steel locker and find a medkit and a pistol.")
            self.player.inventory.extend(["medkit", "pistol"])
        else:
            self.say("It's locked. Maybe someone in the Watch has a key.")

    # ---------- Parser ----------
    def handle(self, raw: str) -> bool:
        line = raw.strip()
        if not line:
            return True
        parts = line.split()
        cmd = parts[0].lower()
        arg = " ".join(parts[1:]) if len(parts) > 1 else ""

        if cmd == 'look':
            self.look()
        elif cmd == 'go':
            if arg:
                self.move(arg.lower())
            else:
                self.say("Go where?")
        elif cmd == 'talk':
            if arg:
                self.talk(arg)
            else:
                self.say("Talk to whom?")
        elif cmd == 'take':
            if arg:
                self.take(arg)
            else:
                self.say("Take what?")
        elif cmd == 'use':
            if arg == 'locker':
                self.open_locker()
            elif arg:
                self.use(arg)
            else:
                self.say("Use what?")
        elif cmd in ('inv','inventory'):
            self.show_inventory()
        elif cmd == 'stats':
            self.show_stats()
        elif cmd == 'quests':
            self.show_quests()
        elif cmd == 'rest':
            self.rest()
        elif cmd == 'save':
            slot = int(arg) if arg.isdigit() else 1
            self.save(slot)
        elif cmd == 'load':
            slot = int(arg) if arg.isdigit() else 1
            self.load(slot)
        elif cmd == 'help':
            self.show_help()
        elif cmd == 'end':
            end = self.check_endings()
            if end:
                self.header("Resolution")
                self.say(end)
                self.say("Thanks for playing!")
                return False
            else:
                self.say("Your story isn't finished yet.")
        elif cmd == 'quit':
            return False
        else:
            self.say("Unknown command. Type 'help' for options.")
        return True

    # ---------- Game Loop ----------
    def intro(self):
        self.header("Lumenfall")
        self.say(
            "Dusk settles on the city of Lumenfall. Factions vie in its alleys: the Watch, the Guild, the Syndicate.\n"
            "Your choices will set its course. Type 'help' for commands."
        )
        self.look()

    def loop(self):
        self.intro()
        running = True
        while running and self.player.is_alive():
            try:
                line = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                print()  # newline
                break
            running = self.handle(line)


if __name__ == '__main__':
    Game().loop()
