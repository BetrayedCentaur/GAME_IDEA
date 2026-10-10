#!/usr/bin/env python3
"""
Lumenfall: a small open-world, choice-driven story in one Python file.
- 13 locations above and below the city, with a map of where you've been
- Three factions, seven quests, bounties, riddles and six endings
- Coins, shops, fishing, tavern dice and a level-up system
- Branching dialog with one-time and conditional choices
- Save/Load to JSON (slots 1-3)

Run: python lumenfall.py
"""
from __future__ import annotations
import json
import os
import random
import sys
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
    defense: int = 0
    price: int = 0        # shop price in coins; sells for half. 0 = no value
    quest: bool = False   # quest items can't be sold

@dataclass
class Choice:
    id: str
    text: str
    effect: str = ""          # e.g. "REP:Watch:+2;QUEST:add:old_docks"
    next: str = ""            # dialog node shown after picking
    requires: str = ""        # e.g. "QUEST:active:lost_blade;ITEM:has:masterwork"
    once: bool = True         # hide after it has been picked

@dataclass
class NPC:
    id: str
    name: str
    role: str
    nodes: Dict[str, List[str]] = field(default_factory=dict)  # node_id -> lines; "start" opens
    choices: List[Choice] = field(default_factory=list)
    hostile: bool = False
    hp: int = 10
    attack: int = 2
    on_defeat: str = ""                     # effects applied when beaten
    xp: int = 0
    coins: Tuple[int, int] = (0, 0)         # coin drop range
    loot: List[Tuple[str, float]] = field(default_factory=list)  # (item id, chance)
    max_hp: int = 0

    def __post_init__(self):
        if not self.max_hp:
            self.max_hp = self.hp

@dataclass
class Tile:
    name: str
    desc: str
    code: str = "???"                                  # 3-letter map label
    exits: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    items: List[str] = field(default_factory=list)
    npcs: List[str] = field(default_factory=list)
    safe_rest: bool = False
    rest_cost: int = 0
    fishing: bool = False
    encounter: str = ""                                # hostile NPC id that may ambush you
    encounter_chance: float = 0.0
    blocked: Dict[str, str] = field(default_factory=dict)  # direction -> NPC id guarding it

@dataclass
class Player:
    name: str = "Wanderer"
    hp: int = 20
    max_hp: int = 20
    attack: int = 3
    inventory: List[str] = field(default_factory=list)
    pos: Tuple[int, int] = (0, 0)
    quests: Dict[str, str] = field(default_factory=dict)  # quest_id -> active/completed/failed
    rep: Dict[str, int] = field(default_factory=lambda: {"Watch": 0, "Guild": 0, "Syndicate": 0})
    flags: List[str] = field(default_factory=list)
    level: int = 1
    xp: int = 0
    coins: int = 10
    kills: Dict[str, int] = field(default_factory=dict)
    visited: List[str] = field(default_factory=list)
    riddles_solved: int = 0

    def is_alive(self) -> bool:
        return self.hp > 0

# -------------------------------
# World Definition
# -------------------------------

ITEMS: Dict[str, Item] = {
    "medkit": Item("medkit", "Medkit", "A basic medical kit.", usable=True, heal=8, price=15),
    "rations": Item("rations", "Rations", "Dried food, keeps you going.", usable=True, heal=4, price=5),
    "tonic": Item("tonic", "Ember Tonic", "Warm and bitter. Mends a lot.", usable=True, heal=15, price=30),
    "blade": Item("blade", "Guild-Forge Blade", "A well-balanced short blade.", attack=2, price=20),
    "pistol": Item("pistol", "Rusty Pistol", "Seen better days but still fires.", attack=3, price=28),
    "masterwork": Item("masterwork", "Anka's Masterwork", "A blade that hums faintly. Anka wants it back.",
                       attack=4, quest=True),
    "coat": Item("coat", "Leather Coat", "Scuffed, but it turns a knife.", defense=1, price=25),
    "buckler": Item("buckler", "Steel Buckler", "A small round shield.", defense=2, price=45),
    "charm": Item("charm", "Clockwork Charm", "Ticks against your chest; blows seem to slow.", defense=3),
    "keywatch": Item("keywatch", "Watch Key", "Opens a locker at the Watch Barracks.", quest=True),
    "lockpick": Item("lockpick", "Lockpicks", "Useful for quiet doors (Syndicate likes this).", price=15),
    "ledger": Item("ledger", "Watch Ledger", "Names of the Watch's informants. Dangerous to carry.", quest=True),
    "relic": Item("relic", "Ember Relic", "A warm stone that glows like a coal. Holy, and valuable.", quest=True),
    "rod": Item("rod", "Fishing Rod", "Bamboo and twine. Try 'fish' by the water.", price=10),
    "eel": Item("eel", "Dock Eel", "Slimy. Someone will buy it.", price=6),
    "silverfin": Item("silverfin", "Silverfin", "A prized catch.", price=18),
    "boot": Item("boot", "Soggy Boot", "Not a fish.", price=1),
    "bottle": Item("bottle", "Message in a Bottle", "Something is rolled up inside. Try using it.", usable=True),
    "rat_tail": Item("rat_tail", "Rat Tail", "Proof of a kill. Pell buys them, oddly.", price=3),
    "trinket": Item("trinket", "Silver Locket", "Tarnished silver with a faded portrait.", price=30),
}

SHOPS: Dict[str, List[str]] = {
    "merchant": ["medkit", "rations", "tonic", "coat", "buckler", "rod"],
    "fence": ["lockpick", "pistol", "tonic"],
}

QUEST_INFO: Dict[str, Tuple[str, str]] = {
    "old_docks": ("Old Docks", "Beat the Dockside Bruiser on the Old Docks, then report to Captain Merrin."),
    "lost_blade": ("Lost Blade", "Recover Anka's Masterwork from the Outskirts and bring it back to her."),
    "quiet_job": ("Quiet Job", "Pick the records cabinet in the Barracks ('use lockpick') and bring Nyx the ledger."),
    "lost_brother": ("Lost Brother", "Find Rook's brother Tam somewhere in the sewers, then tell Rook."),
    "ember_relic": ("Ember Relic", "Take the Ember Relic from the Sewer Depths. Return it to Sister Vael... or sell it."),
    "rat_cull": ("Rat Cull", "Slay 3 sewer rats, then check the bounty board."),
    "warden_bounty": ("Warden Bounty", "Slay the Sewer Warden, then check the bounty board."),
}

# (quest id, kill counter key, kills needed, reward effects)
BOUNTIES = [
    ("rat_cull", "bounty_rats", 3, "COINS:+25;REP:Watch:+1;XP:+5"),
    ("warden_bounty", "warden", 1, "COINS:+50;REP:Watch:+1;XP:+10"),
]

# (riddle, accepted answers, reward effects)
RIDDLES = [
    ("I have hands but cannot clap, and a face that never smiles. What am I?",
     ["clock"], "COINS:+20"),
    ("The more of me you take, the more of me you leave behind. What am I?",
     ["footsteps", "steps", "footprints"], "MAXHP:+5;HEAL:full"),
    ("I fill a room yet take no space, and this city bears my name. What am I?",
     ["light", "lumen"], "ITEM:add:charm"),
]

RUMORS = [
    "The Clockwork Keeper only rewards a sharp tongue. 'answer' her riddles if you can.",
    "Something big nests below the city gate. The sewers stink worse than ever.",
    "Grell at the Smugglers' Cove pays well for holy things. Too well.",
    "Old Pell sells fishing rods. Silverfin fetch a good price this season.",
    "The Watch posts bounties by the Barracks door. Honest coin, they say.",
    "Master Anka hasn't smiled since her masterwork went missing.",
    "A locket was lost in the cistern years ago. Nobody's been brave enough to look.",
]

NPCS: Dict[str, NPC] = {
    "watch_captain": NPC(
        id="watch_captain", name="Captain Merrin", role="Watch",
        nodes={
            "start": [
                "Halt. Lumenfall's safer than it looks—if folk make the right choices.",
                "Rumors say the Syndicate stirs trouble in the Old Docks.",
            ],
            "sworn": ["Good. There's a bruiser on the Old Docks, west of the gate. Clear him out."],
            "supplies": ["Take this key. The locker here has what you'll need."],
            "bounties": ["The board by the door pays honest coin for honest work. Type 'board'."],
            "report": ["The docks are quiet for the first time in months. The Watch won't forget this."],
            "insult": ["Watch your tongue, or the Watch will watch you."],
        },
        choices=[
            Choice("swear", "Swear to aid the Watch", "REP:Watch:+2;QUEST:add:old_docks", "sworn"),
            Choice("supplies", "Ask about supplies", "ITEM:add:keywatch", "supplies"),
            Choice("bounties", "Ask about work that pays", "", "bounties"),
            Choice("report", "Report the docks are clear", "REP:Watch:+2;XP:+5", "report",
                   requires="QUEST:completed:old_docks"),
            Choice("insult", "Insult authority", "REP:Watch:-2", "insult"),
        ],
    ),
    "guild_smith": NPC(
        id="guild_smith", name="Master Anka", role="Guild",
        nodes={
            "start": ["Steel sings when wielded for right causes."],
            "forged": ["Here. Mind the edge—it remembers who swung it."],
            "lost": [
                "Then hear this: scavengers stole my masterwork.",
                "They've holed up in the Outskirts, east of here. Bring it home.",
            ],
            "returned": ["You brought it back. The Guild stands with you, friend."],
        },
        choices=[
            Choice("blade", "Request a forged blade", "ITEM:add:blade;REP:Guild:+1", "forged"),
            Choice("protect", "Offer protection to the Guild", "REP:Guild:+2;QUEST:add:lost_blade", "lost"),
            Choice("return", "Return the masterwork",
                   "ITEM:remove:masterwork;QUEST:complete:lost_blade;REP:Guild:+2;XP:+10", "returned",
                   requires="QUEST:active:lost_blade;ITEM:has:masterwork"),
        ],
    ),
    "syndicate_visor": NPC(
        id="syndicate_visor", name="Visor Nyx", role="Syndicate",
        nodes={
            "start": [
                "We don't break rules; we write the ones people follow.",
                "Quiet hands earn loud rewards.",
            ],
            "job": [
                "The Watch keeps a ledger of informants in its Barracks.",
                "Pick the lock, bring me the book. Quietly.",
            ],
            "delivered": ["Every name, neatly written. The city just changed hands, and nobody noticed."],
            "threat": ["Bold. Foolish, but bold. We'll remember your face."],
        },
        choices=[
            Choice("job", "Take a covert job",
                   "REP:Syndicate:+2;QUEST:add:quiet_job;ITEM:add:lockpick", "job"),
            Choice("deliver", "Hand over the ledger",
                   "ITEM:remove:ledger;QUEST:complete:quiet_job;REP:Syndicate:+2;COINS:+30;XP:+10", "delivered",
                   requires="QUEST:active:quiet_job;ITEM:has:ledger"),
            Choice("threaten", "Threaten the Syndicate", "REP:Syndicate:-2", "threat"),
        ],
    ),
    "merchant": NPC(
        id="merchant", name="Old Pell", role="Market",
        nodes={
            "start": ["Lantern oil, steel, sundries! Coin talks, friend. 'shop' to browse."],
            "tails": ["Alchemists grind 'em up. Don't ask what for. I never do."],
        },
        choices=[
            Choice("browse", "Browse the stall", "SHOP", once=False),
            Choice("tails", "Ask why he buys rat tails", "", "tails"),
        ],
    ),
    "barkeep": NPC(
        id="barkeep", name="Rook", role="Tavern",
        nodes={
            "start": [
                "Welcome to the Lantern. Ale's cheap, rooms are cheaper (5 coins, type 'rest').",
                "Dice table's open if you're feeling lucky: 'dice [bet]'.",
            ],
            "worry": [
                "My little brother Tam went into the sewers on a dare. Three days ago.",
                "The grate's south of the city gate. Please... bring him home.",
            ],
            "tam_home": ["Tam's home? Lanterns bless you. Drinks are on the house. Forever. And take this."],
        },
        choices=[
            Choice("rumor", "Ask for rumors", "RUMOR", once=False),
            Choice("worry", "Ask why he looks worried", "QUEST:add:lost_brother", "worry"),
            Choice("tam", "Tell him Tam is safe", "QUEST:complete:lost_brother;COINS:+40;XP:+10", "tam_home",
                   requires="QUEST:active:lost_brother;FLAG:has:tam_found"),
        ],
    ),
    "cleric": NPC(
        id="cleric", name="Sister Vael", role="Cathedral",
        nodes={
            "start": ["The lanterns of Lumenfall are dimming, child. Can you feel it?"],
            "blessed": ["Be whole. Go gently."],
            "relic": [
                "The Ember Relic once lit every lantern in the city from this altar.",
                "Thieves dragged it into the sewers. Something foul guards it now.",
            ],
            "restored": ["Light returns to Lumenfall. And a little of it stays with you."],
        },
        choices=[
            Choice("bless", "Ask for a blessing (10 coins, full heal)", "COINS:-10;HEAL:full", "blessed",
                   requires="COINS:gte:10", once=False),
            Choice("dimming", "Ask about the dimming lanterns", "QUEST:add:ember_relic", "relic"),
            Choice("return", "Return the Ember Relic",
                   "ITEM:remove:relic;QUEST:complete:ember_relic;MAXHP:+5;HEAL:full;REP:Watch:+1;XP:+15",
                   "restored", requires="QUEST:active:ember_relic;ITEM:has:relic"),
        ],
    ),
    "fence": NPC(
        id="fence", name="Grell", role="Syndicate",
        nodes={
            "start": [
                "Psst. Buying, selling, forgetting. Mostly forgetting. ('shop' to browse.)",
                "Got anything holy? I pay double for holy.",
            ],
            "sold": ["Lovely. Nobody needs to know where it went. Nobody."],
        },
        choices=[
            Choice("wares", "See what Grell is selling", "SHOP", once=False),
            Choice("relic", "Sell the Ember Relic (90 coins)",
                   "ITEM:remove:relic;COINS:+90;REP:Syndicate:+2;QUEST:fail:ember_relic", "sold",
                   requires="ITEM:has:relic"),
        ],
    ),
    "keeper": NPC(
        id="keeper", name="The Clockwork Keeper", role="None",
        nodes={
            "start": [
                "Tick. Tock. Three riddles guard three gifts.",
                "Ask for a riddle, then reply with 'answer [word]'.",
            ],
        },
        choices=[Choice("riddle", "Ask for a riddle", "RIDDLE", once=False)],
    ),
    "tam": NPC(
        id="tam", name="Tam", role="None",
        nodes={
            "start": [
                "You—you're not a rat. Thank the lanterns.",
                "Did Rook send you? I just want to go home.",
            ],
            "bye": ["The way's clear now? I'm running the whole way. Tell Rook I'm sorry!"],
        },
        choices=[Choice("send", "Show him the way out", "FLAG:tam_found;NPC:remove:tam;XP:+5", "bye")],
    ),
    "dock_thug": NPC(
        id="dock_thug", name="Dockside Bruiser", role="Syndicate",
        hostile=True, hp=12, attack=3, xp=8, coins=(5, 12),
        on_defeat="REP:Syndicate:-1;QUEST:complete:old_docks",
    ),
    "scavenger": NPC(
        id="scavenger", name="Scrap Scavenger", role="None",
        hostile=True, hp=9, attack=2, xp=5, coins=(3, 8),
    ),
    "sewer_rat": NPC(
        id="sewer_rat", name="Sewer Rat", role="None",
        hostile=True, hp=6, attack=1, xp=3, coins=(0, 3), loot=[("rat_tail", 0.7)],
    ),
    "warden": NPC(
        id="warden", name="Sewer Warden", role="None",
        hostile=True, hp=28, attack=6, xp=20, coins=(20, 35),
        on_defeat="ITEM:add:relic",
    ),
}

WORLD: Dict[Tuple[int, int], Tile] = {
    (0, 0): Tile("City Gate", "The weathered gate of Lumenfall. Lanterns flicker as dusk gathers. "
                 "A rusted sewer grate sits to the south.",
                 code="GAT", items=["rations"], safe_rest=True),
    (0, 1): Tile("Watch Barracks", "Spartan halls and a scent of oil. A steel locker and a records cabinet "
                 "line the far wall. A bounty board hangs by the door ('board').",
                 code="BAR", npcs=["watch_captain"], safe_rest=True),
    (-1, 1): Tile("Lantern Tavern", "Warm light, loud dice, louder patrons. The best room in the city "
                  "for gossip.",
                  code="TAV", npcs=["barkeep"], safe_rest=True, rest_cost=5),
    (1, 0): Tile("Guild Forge", "Sparks leap from anvils. The Guild shapes more than steel here.",
                 code="FRG", npcs=["guild_smith"]),
    (2, 0): Tile("Outskirts", "Rusted carts and scrap heaps. Something glints beneath a tarp.",
                 code="OUT", items=["masterwork"], npcs=["scavenger"]),
    (1, 1): Tile("Market Square", "Merchants hawk wares; laughter masks worry.",
                 code="MKT", npcs=["merchant"]),
    (1, 2): Tile("Cathedral of Embers", "A vaulted hall around a cold, empty altar. Candles gutter "
                 "in the draft.",
                 code="CTH", npcs=["cleric"], safe_rest=True),
    (2, 1): Tile("Clocktower", "Gears the size of wagon wheels grind overhead. Something brass "
                 "watches you from the shadows.",
                 code="CLK", npcs=["keeper"]),
    (-1, 0): Tile("Old Docks", "Creaking planks, black water. Shadows trade whispers. "
                  "Fish break the surface now and then.",
                  code="DCK", npcs=["syndicate_visor", "dock_thug"], fishing=True),
    (-1, -1): Tile("Smugglers' Cove", "A hidden inlet under the docks. Crates without labels, "
                   "people without names.",
                   code="COV", npcs=["fence"], fishing=True),
    (0, -1): Tile("Sewer Tunnels", "Dripping brick and ankle-deep muck. Something skitters just "
                  "beyond your light.",
                  code="SWR", encounter="sewer_rat", encounter_chance=0.4),
    (0, -2): Tile("Sewer Depths", "A vast chamber where the tunnels meet. Bones crunch underfoot, and something "
                  "huge breathes in the dark. Come prepared. A passage leads east.",
                  code="DEP", npcs=["warden"], blocked={"east": "warden"}),
    (1, -2): Tile("Flooded Cistern", "Still water reflects a vaulted ceiling. Someone has been "
                  "sleeping on a dry ledge.",
                  code="CIS", npcs=["tam"], items=["trinket"]),
}

for (x, y), tile in WORLD.items():
    tile.exits = {
        dname: (x + dx, y + dy)
        for dx, dy, dname in [(0, 1, "north"), (0, -1, "south"), (1, 0, "east"), (-1, 0, "west")]
        if (x + dx, y + dy) in WORLD
    }

# -------------------------------
# Utilities
# -------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")

def ensure_save_dir():
    os.makedirs(SAVE_DIR, exist_ok=True)

def parse_pos(key: str) -> Tuple[int, int]:
    x, y = (int(v) for v in key.strip("() ").split(","))
    return (x, y)

def pos_key(pos: Tuple[int, int]) -> str:
    return f"{pos[0]},{pos[1]}"

def matches(query: str, *names: str) -> bool:
    q = query.lower().strip()
    for n in names:
        n = n.lower().replace("_", " ")
        if q == n or q in n.split():
            return True
    return False

def item_stats(it: Item) -> str:
    bits = []
    if it.attack:
        bits.append(f"+{it.attack} ATK")
    if it.defense:
        bits.append(f"+{it.defense} DEF")
    if it.heal:
        bits.append(f"heals {it.heal}")
    return f" ({', '.join(bits)})" if bits else ""

def qname(qid: str) -> str:
    return QUEST_INFO.get(qid, (qid.replace("_", " ").title(), ""))[0]

# -------------------------------
# Game Systems
# -------------------------------

class Game:
    def __init__(self):
        self.player = Player()
        self.turn = 0
        self.ending_hinted = False
        random.seed()

    # ---------- I/O ----------
    def say(self, text: str):
        print(text)

    def header(self, text: str):
        print("\n== " + text + " ==")

    # ---------- Save/Load ----------
    def save(self, slot: int = 1):
        if slot not in (1, 2, 3):
            self.say("Pick a slot from 1 to 3.")
            return
        ensure_save_dir()
        data = {
            "player": asdict(self.player),
            "turn": self.turn,
            "world_items": {str(k): v.items for k, v in WORLD.items()},
            "world_npcs": {str(k): v.npcs for k, v in WORLD.items()},
            "npc_hp": {nid: n.hp for nid, n in NPCS.items()},
        }
        with open(os.path.join(SAVE_DIR, f"slot{slot}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.say(f"Saved to slot {slot}.")

    def load(self, slot: int = 1):
        path = os.path.join(SAVE_DIR, f"slot{slot}.json")
        if not os.path.exists(path):
            self.say("No save in that slot.")
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.player = Player(**data["player"])
        self.player.pos = tuple(self.player.pos)  # JSON stores it as a list
        for k, items in data.get("world_items", {}).items():
            pos = parse_pos(k)
            if pos in WORLD:
                WORLD[pos].items = items
        for k, npcs in data.get("world_npcs", {}).items():
            pos = parse_pos(k)
            if pos in WORLD:
                WORLD[pos].npcs = npcs
        for nid, hp in data.get("npc_hp", {}).items():
            if nid in NPCS:
                NPCS[nid].hp = hp
        self.turn = data.get("turn", 0)
        self.mark_visited()
        self.say(f"Loaded slot {slot}.")
        self.look()

    # ---------- World ----------
    def tile(self) -> Tile:
        return WORLD[self.player.pos]

    def mark_visited(self):
        k = pos_key(self.player.pos)
        if k not in self.player.visited:
            self.player.visited.append(k)

    def look(self):
        t = self.tile()
        self.header(t.name)
        self.say(t.desc)
        if t.fishing:
            self.say("The water here looks good for fishing.")
        if t.items:
            self.say("Items here: " + ", ".join(ITEMS[i].name for i in t.items))
        if t.npcs:
            self.say("People here: " + ", ".join(NPCS[n].name for n in t.npcs))
        if t.exits:
            labels = []
            for d in t.exits:
                guard = t.blocked.get(d)
                labels.append(f"{d} (blocked)" if guard and guard in t.npcs else d)
            self.say("Exits: " + ", ".join(labels))

    def move(self, direction: str):
        aliases = {"n": "north", "s": "south", "e": "east", "w": "west"}
        direction = aliases.get(direction, direction)
        t = self.tile()
        if direction not in t.exits:
            self.say("You can't go that way.")
            return
        guard = t.blocked.get(direction)
        if guard and guard in t.npcs:
            self.say(f"The {NPCS[guard].name} blocks the way {direction}.")
            return
        self.player.pos = t.exits[direction]
        self.turn += 1
        self.mark_visited()
        self.look()
        self.random_event()
        self.maybe_encounter()

    def random_event(self):
        if random.random() < 0.15:
            self.say(random.choice([
                "A bell tolls in the distance.",
                "You catch a whisper: 'The night favors the bold.'",
                "A street performer flips a coin that never seems to land.",
                "A lamplighter passes, frowning at a lantern that won't catch.",
                "Somewhere below your feet, water rushes through the dark.",
            ]))
        if random.random() < 0.08:
            self.say("You find a packet of rations.")
            self.player.inventory.append("rations")

    def maybe_encounter(self):
        t = self.tile()
        if t.encounter and random.random() < t.encounter_chance:
            npc = NPCS[t.encounter]
            npc.hp = npc.max_hp
            self.say(f"Something lunges from the dark: a {npc.name}!")
            self.combat(t.encounter)

    def hostiles_here(self) -> List[str]:
        return [n for n in self.tile().npcs if NPCS[n].hostile]

    def show_map(self):
        xs = sorted({x for x, _ in WORLD})
        ys = sorted({y for _, y in WORLD}, reverse=True)
        self.header("Map of Lumenfall")
        for y in ys:
            row = ""
            for x in xs:
                pos = (x, y)
                if pos == self.player.pos:
                    row += "[ @ ]"
                elif pos in WORLD and pos_key(pos) in self.player.visited:
                    row += f"[{WORLD[pos].code}]"
                elif pos in WORLD:
                    row += "[ ? ]"
                else:
                    row += "     "
            self.say(row.rstrip())
        known = [f"{WORLD[p].code}={WORLD[p].name}" for p in WORLD if pos_key(p) in self.player.visited]
        self.say("@ = you, ? = unexplored. North is up.")
        self.say("Known: " + ", ".join(known))

    # ---------- Inventory ----------
    def find_in(self, ids: List[str], query: str) -> Optional[str]:
        for iid in ids:
            it = ITEMS[iid]
            if matches(query, it.id, it.name):
                return iid
        return None

    def weapon_bonus(self) -> int:
        return max((ITEMS[i].attack for i in self.player.inventory), default=0)

    def defense(self) -> int:
        return max((ITEMS[i].defense for i in self.player.inventory), default=0)

    def take(self, item_name: str):
        t = self.tile()
        iid = self.find_in(t.items, item_name)
        if not iid:
            self.say("No such item here.")
            return
        guards = self.hostiles_here()
        if guards:
            self.say(f"{NPCS[guards[0]].name} won't let you near it.")
            return
        t.items.remove(iid)
        self.player.inventory.append(iid)
        self.say(f"You take {ITEMS[iid].name}.")

    def use(self, item_name: str) -> bool:
        """Returns True if the item was consumed (used up a combat turn)."""
        iid = self.find_in(self.player.inventory, item_name)
        if not iid:
            self.say("You don't have that.")
            return False
        it = ITEMS[iid]
        if iid == "lockpick":
            self.pick_cabinet()
            return False
        if iid == "bottle":
            self.player.inventory.remove(iid)
            self.say("You uncork the bottle. The note inside reads:")
            self.say(f"  \"{random.choice(RUMORS)}\"")
            self.say("A few coins are tucked into the fold.")
            self.add_coins(10)
            return True
        if it.usable:
            self.player.hp = clamp(self.player.hp + it.heal, 0, self.player.max_hp)
            self.player.inventory.remove(iid)
            self.say(f"You use {it.name}. HP: {self.player.hp}/{self.player.max_hp}")
            return True
        self.say(f"You can't use {it.name} right now.")
        return False

    # ---------- Coins, XP, levels ----------
    def add_coins(self, n: int):
        self.player.coins = max(0, self.player.coins + n)
        sign = "+" if n >= 0 else ""
        self.say(f"Coins {sign}{n} (now {self.player.coins})")
        self.hint_ending()

    def xp_needed(self) -> int:
        return self.player.level * 12

    def gain_xp(self, n: int):
        p = self.player
        p.xp += n
        self.say(f"+{n} XP")
        while p.xp >= self.xp_needed():
            p.xp -= self.xp_needed()
            p.level += 1
            p.max_hp += 4
            p.attack += 1
            p.hp = p.max_hp
            self.say(f"*** Level up! You are now level {p.level}. Max HP {p.max_hp}, ATK {p.attack}. ***")
        self.hint_ending()

    # ---------- Shops ----------
    def shopkeeper(self) -> Optional[str]:
        return next((n for n in self.tile().npcs if n in SHOPS), None)

    def shop(self):
        k = self.shopkeeper()
        if not k:
            self.say("There's no one to trade with here.")
            return
        self.say(f"{NPCS[k].name}'s wares (you have {self.player.coins} coins):")
        for iid in SHOPS[k]:
            it = ITEMS[iid]
            self.say(f"  {it.name:<18} {it.price:>3} coins{item_stats(it)}")
        self.say("Use 'buy [item]' or 'sell [item]' (items sell for half price).")

    def buy(self, query: str):
        k = self.shopkeeper()
        if not k:
            self.say("There's no one to trade with here.")
            return
        iid = self.find_in(SHOPS[k], query)
        if not iid:
            self.say(f"{NPCS[k].name} doesn't sell that.")
            return
        it = ITEMS[iid]
        if self.player.coins < it.price:
            self.say(f"You need {it.price} coins for that. You have {self.player.coins}.")
            return
        self.player.inventory.append(iid)
        self.say(f"You buy {it.name}.")
        self.add_coins(-it.price)

    def sell(self, query: str):
        k = self.shopkeeper()
        if not k:
            self.say("There's no one to trade with here.")
            return
        iid = self.find_in(self.player.inventory, query)
        if not iid:
            self.say("You don't have that.")
            return
        it = ITEMS[iid]
        if it.quest or not it.price:
            self.say(f"{NPCS[k].name} won't take that.")
            return
        self.player.inventory.remove(iid)
        self.say(f"You sell {it.name}.")
        self.add_coins(max(1, it.price // 2))

    # ---------- Activities ----------
    def fish(self):
        t = self.tile()
        if not t.fishing:
            self.say("There's no good water here.")
            return
        if "rod" not in self.player.inventory:
            self.say("You need a fishing rod. Old Pell at the Market sells them.")
            return
        self.turn += 1
        self.say("You cast your line into the black water...")
        r, acc, catch = random.random(), 0.0, None
        for chance, iid in [(0.35, None), (0.30, "eel"), (0.15, "silverfin"), (0.12, "boot"), (0.08, "bottle")]:
            acc += chance
            if r < acc:
                catch = iid
                break
        if catch is None:
            self.say("Nothing bites.")
        else:
            self.player.inventory.append(catch)
            self.say(f"You reel in: {ITEMS[catch].name}!")

    def dice(self, arg: str):
        if self.tile().name != "Lantern Tavern":
            self.say("There's no dice table here.")
            return
        if not arg.isdigit() or not 1 <= int(arg) <= 50:
            self.say("Bet between 1 and 50 coins: dice [bet]")
            return
        bet = int(arg)
        if bet > self.player.coins:
            self.say(f"You only have {self.player.coins} coins.")
            return
        you = random.randint(1, 6) + random.randint(1, 6)
        house = random.randint(1, 6) + random.randint(1, 6)
        self.say(f"You roll {you}. The house rolls {house}.")
        if you > house:
            self.say("You win! The table cheers.")
            self.add_coins(bet)
        elif you < house:
            self.say("The house wins.")
            self.add_coins(-bet)
        else:
            self.say("A tie. Your bet comes back to you.")

    def riddle(self):
        i = self.player.riddles_solved
        if i >= len(RIDDLES):
            self.say("\"No riddles remain. You have earned all my gifts.\"")
        else:
            self.say(f"\"Riddle {i + 1} of {len(RIDDLES)}: {RIDDLES[i][0]}\"")
            self.say("(Reply with 'answer [word]'.)")

    def answer(self, arg: str):
        if "keeper" not in self.tile().npcs:
            self.say("No one here is asking riddles.")
            return
        i = self.player.riddles_solved
        if i >= len(RIDDLES):
            self.say("The Keeper is silent. You've solved every riddle.")
            return
        if not arg:
            self.say("Answer what? Ask the Keeper for a riddle first.")
            return
        _, answers, reward = RIDDLES[i]
        words = arg.lower().replace(".", "").split()
        if any(w in answers for w in words):
            self.say("\"Correct.\" A brass drawer clicks open.")
            self.player.riddles_solved += 1
            self.apply_effects(reward)
            self.gain_xp(10)
            if self.player.riddles_solved < len(RIDDLES):
                self.say("(Ask for another riddle when you're ready.)")
        else:
            self.say("The gears grind disapprovingly. \"Wrong. Think, and return.\"")

    def board(self):
        if self.tile().name != "Watch Barracks":
            self.say("There's no bounty board here.")
            return
        p = self.player
        self.header("Bounty Board")
        for qid, key, need, reward in BOUNTIES:
            status = p.quests.get(qid)
            if status == "completed":
                self.say(f"- {qname(qid)}: paid out.")
            elif status is None:
                self.say(f"- {qname(qid)}: {QUEST_INFO[qid][1]}")
                self.apply_effects(f"QUEST:add:{qid}")
            elif p.kills.get(key, 0) >= need:
                self.say(f"- {qname(qid)}: done! A clerk hands you your reward.")
                self.apply_effects(f"QUEST:complete:{qid};{reward}")
            else:
                self.say(f"- {qname(qid)}: {p.kills.get(key, 0)}/{need}")

    # ---------- Conditions & Effects ----------
    def check(self, requires: str) -> bool:
        for part in filter(None, (p.strip() for p in requires.split(";"))):
            kind, op, arg = part.split(":", 2)
            if kind == "QUEST":
                status = self.player.quests.get(arg)
                ok = (op == "active" and status == "active") or \
                     (op == "completed" and status == "completed") or \
                     (op == "none" and status is None)
            elif kind == "ITEM":
                ok = (arg in self.player.inventory) == (op == "has")
            elif kind == "FLAG":
                ok = (arg in self.player.flags) == (op == "has")
            elif kind == "COINS":
                ok = self.player.coins >= int(arg)
            elif kind == "LEVEL":
                ok = self.player.level >= int(arg)
            else:
                ok = False
            if not ok:
                return False
        return True

    def apply_effects(self, effect_str: str):
        p = self.player
        for part in filter(None, (s.strip() for s in effect_str.split(";"))):
            if part.startswith("REP:"):
                _, faction, delta = part.split(":")
                p.rep[faction] = p.rep.get(faction, 0) + int(delta)
                self.say(f"Reputation with {faction}: {p.rep[faction]}")
            elif part.startswith("QUEST:add:"):
                qid = part.split(":", 2)[2]
                if qid not in p.quests:
                    p.quests[qid] = "active"
                    self.say(f"Quest started: {qname(qid)}")
            elif part.startswith("QUEST:complete:"):
                qid = part.split(":", 2)[2]
                if p.quests.get(qid) == "active":
                    p.quests[qid] = "completed"
                    self.say(f"Quest completed: {qname(qid)}")
            elif part.startswith("QUEST:fail:"):
                qid = part.split(":", 2)[2]
                if p.quests.get(qid) == "active":
                    p.quests[qid] = "failed"
                    self.say(f"Quest failed: {qname(qid)}")
            elif part.startswith("ITEM:add:"):
                iid = part.split(":", 2)[2]
                p.inventory.append(iid)
                self.say(f"Received: {ITEMS[iid].name}")
            elif part.startswith("ITEM:remove:"):
                iid = part.split(":", 2)[2]
                if iid in p.inventory:
                    p.inventory.remove(iid)
                    self.say(f"Handed over: {ITEMS[iid].name}")
            elif part.startswith("FLAG:"):
                flag = part.split(":", 1)[1]
                if flag not in p.flags:
                    p.flags.append(flag)
            elif part.startswith("NPC:remove:"):
                nid = part.split(":", 2)[2]
                if nid in self.tile().npcs:
                    self.tile().npcs.remove(nid)
            elif part.startswith("COINS:"):
                self.add_coins(int(part.split(":", 1)[1]))
            elif part.startswith("XP:"):
                self.gain_xp(int(part.split(":", 1)[1]))
            elif part.startswith("MAXHP:"):
                p.max_hp += int(part.split(":", 1)[1])
                self.say(f"Max HP is now {p.max_hp}.")
            elif part.startswith("HEAL:"):
                amt = part.split(":", 1)[1]
                p.hp = p.max_hp if amt == "full" else clamp(p.hp + int(amt), 0, p.max_hp)
                self.say(f"HP: {p.hp}/{p.max_hp}")
            elif part == "SHOP":
                self.shop()
            elif part == "RUMOR":
                self.say(f"\"{random.choice(RUMORS)}\"")
            elif part == "RIDDLE":
                self.riddle()
        self.hint_ending()

    def hint_ending(self):
        if not self.ending_hinted and self.check_endings():
            self.ending_hinted = True
            self.say("(An ending is within reach. Type 'end' when you're ready, or keep exploring.)")

    # ---------- NPC / Dialog ----------
    def talk(self, who: str):
        target_id = next(
            (nid for nid in self.tile().npcs
             if matches(who, nid, NPCS[nid].name) or who.lower() == NPCS[nid].name.lower()),
            None,
        )
        if not target_id:
            self.say("No one here by that name.")
            return
        npc = NPCS[target_id]
        if npc.hostile:
            self.say(f"{npc.name} snarls—no words, only fists.")
            self.combat(target_id)
            return

        self.header(npc.name)
        node = "start"
        while True:
            for line in npc.nodes.get(node, []):
                self.say(f"\"{line}\"")
            opts = [
                c for c in npc.choices
                if self.check(c.requires)
                and not (c.once and f"{npc.id}:{c.id}" in self.player.flags)
            ]
            if not opts or target_id not in self.tile().npcs:
                if target_id in self.tile().npcs:
                    self.say(f"{npc.name} has nothing more to say for now.")
                return
            self.say("Choices:")
            for i, c in enumerate(opts, 1):
                self.say(f"  {i}. {c.text}")
            sel = input("> Pick (number) or Enter to leave: ").strip()
            if not sel.isdigit() or not (1 <= int(sel) <= len(opts)):
                return
            c = opts[int(sel) - 1]
            self.say(f"You chose: {c.text}")
            if c.once:
                self.player.flags.append(f"{npc.id}:{c.id}")
            self.apply_effects(c.effect)
            node = c.next

    # ---------- Combat ----------
    def combat(self, npc_id: str):
        npc = NPCS[npc_id]
        p = self.player
        self.header(f"Combat: {npc.name}")
        while npc.hp > 0 and p.is_alive():
            self.say(f"Your HP {p.hp}/{p.max_hp} | {npc.name} HP {npc.hp}/{npc.max_hp}")
            cmd = input("> (attack/use [item]/run): ").strip().lower()
            if cmd.startswith("use "):
                if not self.use(cmd[4:]):
                    continue
            elif cmd == "run":
                if random.random() < 0.5:
                    self.say("You slip away into the shadows!")
                    return
                self.say("You fail to escape!")
            elif cmd in ("attack", "a"):
                dmg = p.attack + random.randint(0, 2) + self.weapon_bonus()
                if random.random() < 0.1:
                    dmg *= 2
                    self.say("Critical hit!")
                npc.hp = max(0, npc.hp - dmg)
                self.say(f"You strike for {dmg}!")
                if npc.hp <= 0:
                    self.defeat(npc_id)
                    return
            else:
                self.say("Type attack, use [item], or run.")
                continue
            raw = npc.attack + random.randint(0, 2)
            edmg = max(1, raw - self.defense())
            p.hp = max(0, p.hp - edmg)
            blocked = raw - edmg
            self.say(f"{npc.name} hits for {edmg}!" + (f" (your gear blocks {blocked})" if blocked else ""))
        if not p.is_alive():
            self.game_over()

    def defeat(self, npc_id: str):
        npc = NPCS[npc_id]
        p = self.player
        self.say(f"{npc.name} falls.")
        if npc_id in self.tile().npcs:
            self.tile().npcs.remove(npc_id)
        p.kills[npc_id] = p.kills.get(npc_id, 0) + 1
        if npc_id == "sewer_rat" and p.quests.get("rat_cull") == "active":
            p.kills["bounty_rats"] = p.kills.get("bounty_rats", 0) + 1
            self.say(f"(Rat Cull: {min(3, p.kills['bounty_rats'])}/3)")
        lo, hi = npc.coins
        if hi:
            self.add_coins(random.randint(lo, hi))
        for iid, chance in npc.loot:
            if random.random() < chance:
                p.inventory.append(iid)
                self.say(f"Looted: {ITEMS[iid].name}")
        self.apply_effects(npc.on_defeat)
        if npc.xp:
            self.gain_xp(npc.xp)

    def rest(self):
        t = self.tile()
        p = self.player
        if self.hostiles_here():
            self.say("Not with enemies watching.")
        elif t.rest_cost:
            if p.coins < t.rest_cost:
                self.say(f"A room costs {t.rest_cost} coins. You can't afford it.")
                return
            self.say(f"You rent a room for the night and wake fully rested.")
            self.add_coins(-t.rest_cost)
            p.hp = p.max_hp
            self.say(f"HP: {p.hp}/{p.max_hp}")
        elif t.safe_rest:
            heal = random.randint(4, 8)
            p.hp = clamp(p.hp + heal, 0, p.max_hp)
            self.say(f"You rest safely and recover {heal} HP. ({p.hp}/{p.max_hp})")
        else:
            self.say("This place is too risky to rest.")

    # ---------- Item-gated interactions ----------
    def open_locker(self):
        if self.tile().name != "Watch Barracks":
            self.say("No locker here.")
        elif "locker_opened" in self.player.flags:
            self.say("The locker stands open and empty.")
        elif "keywatch" in self.player.inventory:
            self.say("You open the steel locker and find a medkit and a pistol.")
            self.player.inventory.extend(["medkit", "pistol"])
            self.player.flags.append("locker_opened")
        else:
            self.say("It's locked. Maybe someone in the Watch has a key.")

    def pick_cabinet(self):
        if self.tile().name != "Watch Barracks":
            self.say("Nothing here worth picking.")
        elif "ledger_stolen" in self.player.flags:
            self.say("The cabinet's already been emptied.")
        elif self.player.quests.get("quiet_job") != "active":
            self.say("You eye the records cabinet, but you have no reason to risk it.")
        else:
            self.say("Tumblers click. Inside the records cabinet: a thick ledger of names.")
            self.player.flags.append("ledger_stolen")
            self.apply_effects("ITEM:add:ledger;REP:Watch:-1")

    # ---------- Endings ----------
    def check_endings(self) -> Optional[str]:
        q, r, p = self.player.quests, self.player.rep, self.player
        if q.get("ember_relic") == "completed" and q.get("lost_brother") == "completed" and p.level >= 3:
            return ("ENDING: The Lamplighter — Beholden to no faction, you rekindle the city's "
                    "lanterns and bring its lost home.")
        if p.coins >= 250:
            return ("ENDING: Golden Lantern — You buy the Lantern Tavern, then the docks, "
                    "then everyone's silence.")
        for faction, val in r.items():
            if val >= 5:
                return f"ENDING: {faction} Triumph — Your deeds secure {faction}'s vision for Lumenfall."
        if q.get("old_docks") == "completed" and r.get("Watch", 0) >= 3:
            return "ENDING: Dawn Watch — The docks are pacified and the Watch strengthens rule of law."
        if q.get("quiet_job") == "completed" and r.get("Syndicate", 0) >= 3:
            return "ENDING: Shadow Accord — The Syndicate ushers in an age of controlled chaos."
        if q.get("lost_blade") == "completed" and r.get("Guild", 0) >= 3:
            return "ENDING: Forged Future — The Guild's craft rebuilds the city's hope."
        return None

    def game_over(self):
        self.header("You have fallen")
        self.say("The city remembers the brave—and the foolish.")
        sys.exit(0)

    # ---------- UI ----------
    def show_help(self):
        self.say("""
Getting around
  look, map                   — describe this place / show explored map
  go [dir]  (or n/e/s/w)      — move north, east, south or west
People & quests
  talk [name]                 — talk or fight (just 'talk' if one person is here)
  quests                      — your quests and what to do next
  board                       — the bounty board (Watch Barracks)
  answer [word]               — answer a riddle (Clocktower)
Items & trade
  take [item], use [item]     — pick up / use (medkit, lockpick, bottle...)
  use locker                  — try the Barracks locker
  inv                         — inventory
  shop, buy [item], sell [x]  — trade with a merchant
Activities
  fish                        — fish by the water (needs a rod)
  dice [bet]                  — gamble at the Lantern Tavern
  rest                        — rest where it's safe
Game
  stats, save [1-3], load [1-3], end, help, quit
        """.strip())

    def show_inventory(self):
        p = self.player
        self.say(f"Coins: {p.coins}")
        if not p.inventory:
            self.say("Inventory empty.")
            return
        self.say("Inventory:")
        counts: Dict[str, int] = {}
        for iid in p.inventory:
            counts[iid] = counts.get(iid, 0) + 1
        for iid, n in counts.items():
            it = ITEMS[iid]
            qty = f" x{n}" if n > 1 else ""
            self.say(f"- {it.name}{qty}{item_stats(it)}: {it.desc}")

    def show_stats(self):
        p = self.player
        self.say(f"Level {p.level} ({p.xp}/{self.xp_needed()} XP) | HP {p.hp}/{p.max_hp} | Coins {p.coins}")
        self.say(f"ATK {p.attack} (+{self.weapon_bonus()} weapon) | DEF {self.defense()}")
        self.say("Reputation: " + ", ".join(f"{k} {v}" for k, v in p.rep.items()))
        self.say(f"Riddles solved: {p.riddles_solved}/{len(RIDDLES)} | Places explored: "
                 f"{len(p.visited)}/{len(WORLD)}")

    def show_quests(self):
        if not self.player.quests:
            self.say("No quests yet. Talk to people around the city.")
            return
        for q, st in self.player.quests.items():
            self.say(f"- {qname(q)} [{st}]")
            if st == "active" and q in QUEST_INFO:
                self.say(f"    {QUEST_INFO[q][1]}")

    # ---------- Parser ----------
    def handle(self, raw: str) -> bool:
        parts = raw.strip().split()
        if not parts:
            return True
        cmd, arg = parts[0].lower(), " ".join(parts[1:])

        if cmd in ("n", "s", "e", "w", "north", "south", "east", "west"):
            self.move(cmd)
        elif cmd == "look":
            self.look()
        elif cmd == "map":
            self.show_map()
        elif cmd == "go":
            self.move(arg.lower()) if arg else self.say("Go where?")
        elif cmd == "talk":
            if arg:
                self.talk(arg)
            else:
                friendly = [n for n in self.tile().npcs if not NPCS[n].hostile]
                if len(friendly) == 1:
                    self.talk(NPCS[friendly[0]].name)
                else:
                    self.say("Talk to whom?")
        elif cmd == "take":
            self.take(arg) if arg else self.say("Take what?")
        elif cmd == "use":
            if arg.lower() == "locker":
                self.open_locker()
            elif arg:
                self.use(arg)
            else:
                self.say("Use what?")
        elif cmd in ("inv", "inventory", "i"):
            self.show_inventory()
        elif cmd == "shop":
            self.shop()
        elif cmd == "buy":
            self.buy(arg) if arg else self.say("Buy what?")
        elif cmd == "sell":
            self.sell(arg) if arg else self.say("Sell what?")
        elif cmd == "fish":
            self.fish()
        elif cmd == "dice":
            self.dice(arg)
        elif cmd == "answer":
            self.answer(arg)
        elif cmd == "board":
            self.board()
        elif cmd == "stats":
            self.show_stats()
        elif cmd == "quests":
            self.show_quests()
        elif cmd == "rest":
            self.rest()
        elif cmd == "save":
            self.save(int(arg) if arg.isdigit() else 1)
        elif cmd == "load":
            self.load(int(arg) if arg.isdigit() else 1)
        elif cmd == "help":
            self.show_help()
        elif cmd == "end":
            end = self.check_endings()
            if end:
                self.header("Resolution")
                self.say(end)
                self.say("Thanks for playing!")
                return False
            self.say("Your story isn't finished yet.")
        elif cmd == "quit":
            return False
        else:
            self.say("Unknown command. Type 'help' for options.")
        return True

    # ---------- Game Loop ----------
    def intro(self):
        self.header("Lumenfall")
        self.say(
            "Dusk settles on the city of Lumenfall, and its lanterns are dimming one by one.\n"
            "Factions vie in its alleys: the Watch, the Guild, the Syndicate.\n"
            "Your choices will set its course. Type 'help' for commands, 'map' to get your bearings."
        )
        self.mark_visited()
        self.look()

    def loop(self):
        self.intro()
        while self.player.is_alive():
            try:
                line = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not self.handle(line):
                break


if __name__ == "__main__":
    Game().loop()