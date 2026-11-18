"""
The silhouette stories' vocabulary: the places a shot can happen in (with their lights), what he can do in each, who else
can be there and how, the moods of the eyes, the events, the camera's moves and how a shot enters. Agent 2 writes every
shot in these words (agents/story.py), Agent 3 draws them (tools/silhouette_render.py). Plain data: no drawing code, so
the dashboard can read it too.
"""

SETS = {
    "desk_room": ("his room: his desk under the big window with the skyline, the flip clock, the hanging lamp, the laptop",
                  ["dusk", "night", "dawn", "day"]),
    "bedroom": ("his bedroom: the bed, a window over the nightstand with a red alarm clock, a wardrobe",
                ["night", "dawn", "day", "dusk"]),
    "kitchen": ("the kitchen of his flat: a small table under a hanging lamp with the bills on it, the counter, the fridge",
                ["night", "dusk", "day", "dawn"]),
    "hallway": ("the narrow hall of his flat: the front door (open when someone stands in it), coats, a bare bulb",
                ["night", "day", "dusk"]),
    "street": ("a city street, seen from the side: shop windows, street lamps, wet pavement in rain",
               ["night", "dusk", "day", "dawn"]),
    "hospital": ("his mother's hospital room: her bed, the heart monitor, the drip, a window, a small lamp",
                 ["night", "day", "dawn", "dusk"]),
    "office": ("an office floor: a wall of windows onto the city, desks and screens, the boss's glass door",
               ["day", "dusk", "night"]),
    "cafe": ("a small café: a round table for two by a big window, a pendant lamp, the counter",
             ["day", "dusk", "night"]),
    "rooftop": ("a flat roof above the city: the parapet, a water tank, string lights, the whole sky",
                ["dawn", "dusk", "night", "day"]),
    "park": ("a city park: big trees, a path, a bench, lamps; where people run at dawn",
             ["dawn", "day", "dusk", "night"]),
    "bright_office": ("the life he built: a bright meeting room with a glass wall onto the city, a long table",
                      ["day", "dusk"]),
    "new_flat": ("the home he made: a tall window onto the city, a sofa, a warm floor lamp, plants, books",
                 ["day", "dusk", "night", "dawn"]),
}
POSES = {
    "none": "nobody: the place alone",
    "typing": "at a desk, typing", "sitting": "sitting (at a desk or table, on a bed's edge, a bench, a sofa, a chair)",
    "slumped": "sitting, slumped, shoulders down", "head_in_hands": "sitting, his head sunk into his hands",
    "phone": "looking at his phone, its cold glow on him", "lying_awake": "lying awake in bed, the phone over his face",
    "asleep": "asleep in bed", "standing": "standing", "walking": "walking", "running": "running",
    "floor": "sitting on the floor, his back to a wall, knees up", "at_window": "standing at a window, looking out",
    "pushups": "doing push-ups", "carrying_box": "carrying a cardboard box (his things)", "at_door": "at a door, knocking",
}
SET_POSES = {
    "desk_room": {"typing": "desk", "sitting": "desk", "slumped": "desk", "head_in_hands": "desk", "phone": "desk"},
    "bedroom": {"lying_awake": "bed", "asleep": "bed", "sitting": "edge", "slumped": "edge", "head_in_hands": "edge",
                "phone": "bed", "standing": "stand", "at_window": "window", "floor": "floor", "pushups": "pushup",
                "walking": "walk"},
    "kitchen": {"sitting": "sit", "slumped": "sit", "head_in_hands": "sit", "phone": "sit", "standing": "stand",
                "walking": "walk"},
    "hallway": {"at_door": "door", "standing": "stand", "floor": "floor", "walking": "walk", "carrying_box": "walk",
                "phone": "stand"},
    "street": {"walking": "walk", "standing": "stand", "running": "run", "carrying_box": "walk", "phone": "stand"},
    "hospital": {"standing": "stand", "sitting": "chair", "slumped": "chair", "head_in_hands": "chair"},
    "office": {"typing": "desk", "sitting": "desk", "slumped": "desk", "head_in_hands": "desk", "standing": "stand",
               "carrying_box": "walk", "walking": "walk", "phone": "stand"},
    "cafe": {"sitting": "sit", "slumped": "sit", "head_in_hands": "sit", "phone": "sit", "standing": "stand",
             "walking": "walk"},
    "rooftop": {"standing": "stand", "at_window": "stand", "pushups": "pushup", "sitting": "sit", "floor": "floor",
                "phone": "stand", "walking": "walk", "running": "run"},
    "park": {"running": "run", "walking": "walk", "pushups": "pushup", "sitting": "sit", "standing": "stand",
             "phone": "stand"},
    "bright_office": {"standing": "stand", "at_window": "window", "typing": "desk", "sitting": "desk", "walking": "walk"},
    "new_flat": {"standing": "stand", "at_window": "window", "sitting": "sofa", "walking": "walk", "phone": "stand"},
}
OTHERS = {
    "none": "nobody else", "mother": "his mother, older, silver hair", "woman": "the woman he loved, long hair, a coat",
    "boss": "his boss, in a suit", "landlord": "the landlord, a big man in a cap", "doctor": "a doctor in a white coat",
    "friend": "a friend", "crowd": "other people (colleagues, passers-by, runners)",
}
OTHER_POSES = ["standing", "sitting", "leaving", "lying", "offering", "arms_crossed"]
SET_OTHERS = {  # who can be in each place, and how ({who: {their pose: mark}})
    "desk_room": {},
    "bedroom": {},
    "kitchen": {"mother": {"sitting": "sit_other"}, "woman": {"standing": "stand_other", "leaving": "leave"},
                "friend": {"sitting": "sit_other", "standing": "stand_other"}},
    "hallway": {"landlord": {"standing": "doorway", "offering": "doorway"}, "woman": {"leaving": "leave", "standing": "doorway"},
                "friend": {"standing": "doorway"}},
    "street": {"woman": {"standing": "stand_other", "leaving": "walk_away", "offering": "stand_other"},
               "friend": {"standing": "stand_other"}, "crowd": {"standing": "crowd", "leaving": "crowd"}},
    "hospital": {"mother": {"lying": "bed"}, "doctor": {"standing": "doctor"}},
    "office": {"boss": {"standing": "boss", "arms_crossed": "boss", "offering": "boss"}},   # (its colleagues are drawn in by day)
    "cafe": {"woman": {"sitting": "sit_other", "standing": "stand_other", "leaving": "leave"},
             "friend": {"sitting": "sit_other", "standing": "stand_other"}},
    "rooftop": {},
    "park": {"crowd": {"leaving": "crowd", "standing": "crowd"}},
    "bright_office": {"boss": {"standing": "other", "offering": "other", "arms_crossed": "other"},
                      "woman": {"standing": "other", "offering": "other"}, "crowd": {"sitting": "crowd"}},
    "new_flat": {"mother": {"sitting": "sofa_other"}, "woman": {"standing": "door", "offering": "door"},
                 "friend": {"standing": "door"}},
}
MOODS = ["tired", "open", "wide", "closed", "sad", "determined", "soft", "happy", "angry", "worried"]  # (silhouette.MOODS)
EVENTS = {
    "none": "nothing happens: life, breath, a blink",
    "head_turn": "his head turns to the camera and his eyes spring wide (the look's signature moment; use it rarely)",
    "look_up": "he lifts his head and looks up", "look_down": "he lowers his head",
    "eyes_open": "his eyes open (he wakes, or comes to)", "eyes_close": "his eyes close",
    "nod": "a small nod", "shake_head": "a slow shake of the head (a calm no)",
    "phone_buzz": "his phone buzzes", "lamp_off": "the lamp switches off (the room goes dark)",
    "lights_on": "the city's windows light up behind him (desk_room)", "clock_flip": "the flip clock turns a minute (desk_room)",
    "knock": "he knocks on the door (at_door)",
}
CAMERA = ["hold", "push_in", "pull_out", "pan_left", "pan_right"]
ENTER = ["cut", "fade", "lights_out"]


# === the library of the composed places (step 2 of the 2026-11-16 plan): Agent 3's storyboard designs every story's
# places, people and shots from these words; tools/silhouette_scene.py, _props.py, _actions.py and _fx.py draw them =====
PLACE_KINDS = {
    "room": "a room of a home or a workplace (bedroom, living room, kitchen, bathroom, office, shop, workshop, a "
            "restaurant's kitchen, a gym, a clinic...): its things make it what it is",
    "hall": "a big hall with a high ceiling (a conference hall with a stage, a sports hall, a banquet hall, a waiting hall)",
    "corridor": "a long corridor: doors along the wall, ceiling lamps in a row (a hospital's, an office's, a block of flats')",
    "street": "a city street: shop fronts and buildings, street lamps, the pavement",
    "houses": "a quiet street of houses: front gardens, fences, trees",
    "bridge": "a bridge over a river at the edge of the city, the far bank's lights",
    "nature": "out in nature: NATURE (hills, mountains, sea and beach, field, forest, lake)",
    "car": "inside a car, seen through its side window, the world sliding past",
    "bus": "inside a bus: seats, windows with the city passing, grab poles",
    "train": "inside a train: seats facing each other, big windows with the land rushing past",
}
WALLS = {"plum": "#5A4048", "mauve": "#6A4E5A", "rose": "#6A3E48", "slate": "#3E4058", "navy": "#2E3450",
         "teal": "#2E4A50", "olive": "#4A4A38", "sand": "#6A5A48", "grey": "#4A4650", "cream": "#7A6A5A",
         "white": "#8A8090", "brick": "#5A3A34", "green": "#3A4A40"}
FLOORS = {"wood": "#2A1E22", "tiles": "#2A2630", "carpet": "#2E2234", "concrete": "#2A2830", "stone": "#2C2830"}
WINDOWS = ("none", "small", "big", "wide", "tall")
VIEWS = ("city", "houses", "trees", "sea", "hills", "mountains", "fields")
NATURE = ("hills", "mountains", "sea", "field", "forest", "lake")
WEATHER = ("clear", "rain", "snow", "fog")
EFFECTS = {  # name: what it is (the storyboard's words)
    "fire": "a fire: flames, embers and their warm light (a burning room, a house on fire, a fireplace, a campfire)",
    "smoke": "smoke rising and gathering under the ceiling or into the sky",
    "emergency": "an ambulance's or a police car's lights washing the place red and blue, slowly",
    "snow": "snow falling (outdoors, or beyond the window)",
    "fog": "fog drifting in soft banks",
    "party": "party lights: strings of warm coloured bulbs, soft coloured light moving on the walls",
    "spotlight": "a spotlight from above on him, the rest of the place dimmed (a stage, a lonely moment)",
}

# name: (group, what it is, width, layer, where, tall?, its surface (dx0, dx1, height) for small things, or None)
PROPS = {
    # home
    "bed": ("home", "a bed (he lies in it under the blanket; sits on its edge)", 790, "mid", "in", False, (150, 330, 104)),
    "sofa": ("home", "a sofa (two seats facing each other; he can lie on it)", 450, "mid", "in", False, None),
    "armchair": ("home", "an armchair", 210, "mid", "in", False, None),
    "dining_table": ("home", "a dining table with two chairs, plates on it", 600, "mid", "in", False, (-150, 150, 150)),
    "chair": ("home", "a single chair", 130, "mid", "in", False, None),
    "desk": ("home", "a desk with a computer screen, a keyboard and a chair", 470, "mid", "in", False, (-140, -100, 140)),
    "stove": ("home", "a kitchen stove with a pan and a pot, a hood above", 240, "back", "in", False, None),
    "fridge": ("home", "a fridge", 130, "back", "in", True, None),
    "counter": ("home", "a kitchen counter with a sink and cupboards", 400, "back", "in", False, (-180, -30, 160)),
    "basin": ("home", "a bathroom basin with a mirror above it", 170, "back", "in", True, None),
    "wardrobe": ("home", "a wardrobe", 240, "back", "in", True, None),
    "bookcase": ("home", "a tall bookcase full of books", 250, "back", "in", True, None),
    "tv": ("home", "a TV on a low cabinet (its cold glow when it's on)", 340, "back", "in", False, (110, 150, 110)),
    "floor_lamp": ("home", "a floor lamp (warm light at dusk and night)", 100, "back", "in", True, None),
    "nightstand": ("home", "a nightstand with a small lamp and an alarm clock", 120, "back", "in", False, (-52, 52, 95)),
    "plant": ("home", "a potted plant", 110, "back", "both", False, None),
    "coffee_table": ("home", "a low coffee table", 260, "mid", "in", False, (-110, 110, 82)),
    "door": ("home", "a door (closed, or open with light behind it)", 300, "back", "in", True, None),
    "rug": ("home", "a rug on the floor", 520, "floor", "in", False, None),
    "fireplace": ("home", "a fireplace with a fire burning, a mantel", 360, "back", "in", False, (-180, 180, 312)),
    # on the walls
    "photos": ("wall", "framed photos", 230, "wall", "in", False, None),
    "poster": ("wall", "a big framed picture", 200, "wall", "in", False, None),
    "clock": ("wall", "a round wall clock", 100, "wall", "in", False, None),
    "shelf": ("wall", "a wall shelf with books", 250, "wall", "in", False, (-110, 110, 0)),
    "cabinets": ("wall", "kitchen wall cupboards", 380, "wall", "in", False, None),
    "whiteboard": ("wall", "a whiteboard with a chart", 360, "wall", "in", False, None),
    "screen": ("wall", "a presentation screen with a chart (glowing)", 380, "wall", "in", False, None),
    "notice_board": ("wall", "a notice board with papers pinned to it", 230, "wall", "in", False, None),
    "certificates": ("wall", "framed certificates", 200, "wall", "in", False, None),
    "calendar": ("wall", "a calendar with days crossed off", 120, "wall", "in", False, None),
    "tool_wall": ("wall", "a pegboard of tools", 340, "wall", "in", False, None),
    "mirror": ("wall", "a mirror on the wall", 150, "wall", "in", False, None),
    # work
    "office_row": ("work", "a back row of office desks with screens (colleagues at them by day)", 600, "back", "in", False,
                   None),
    "meeting_table": ("work", "a long meeting table with chairs at its ends", 700, "mid", "in", False, (-220, 220, 150)),
    "shop_counter": ("work", "a shop counter with a till (a customer one side, the shopkeeper the other)", 380, "mid",
                     "in", False, (-150, 40, 170)),
    "shop_shelves": ("work", "shop shelves full of goods", 400, "back", "in", True, None),
    "workbench": ("work", "a workbench with a vice and tools", 400, "mid", "in", False, (-170, 60, 175)),
    "chef_range": ("work", "a restaurant kitchen's steel range, pots, hanging pans", 460, "back", "in", False, None),
    "prep_counter": ("work", "a steel prep counter with a chopping board", 380, "mid", "in", False, (40, 170, 170)),
    "podium": ("work", "a podium with a microphone (he speaks behind it)", 160, "mid", "in", False, None),
    "stage": ("work", "a stage with curtains (people on it stand higher)", 1100, "back", "in", True, None),
    "audience": ("work", "an audience's heads in the foreground, out of focus", 1000, "fore", "in", False, None),
    "filing_cabinet": ("work", "a filing cabinet", 120, "back", "in", False, (-45, 45, 300)),
    "water_cooler": ("work", "a water cooler", 90, "back", "in", False, None),
    # health and the gym
    "hospital_bed": ("health", "a hospital bed with a drip stand", 760, "mid", "in", False, None),
    "heart_monitor": ("health", "a heart monitor with its moving trace", 150, "back", "in", True, None),
    "waiting_chairs": ("health", "a row of waiting-room chairs", 460, "mid", "in", False, None),
    "weights": ("health", "a rack of dumbbells", 340, "back", "in", False, None),
    "punching_bag": ("health", "a heavy punching bag hanging from the ceiling", 170, "mid", "both", True, None),
    "treadmill": ("health", "a treadmill", 340, "mid", "in", False, None),
    "gym_mat": ("health", "an exercise mat on the floor", 330, "floor", "in", False, None),
    # outdoors
    "tree": ("outdoors", "a big leafy tree", 360, "back", "out", True, None),
    "pine": ("outdoors", "a pine tree", 240, "back", "out", True, None),
    "house": ("outdoors", "a small house: pitched roof, chimney, lit windows at night", 520, "back", "out", True, None),
    "shopfront": ("outdoors", "a shop's front: a lit window, an awning, a door", 520, "back", "out", True, None),
    "car": ("outdoors", "a parked car (its lights on at night)", 860, "mid", "out", False, None),
    "ambulance": ("outdoors", "an ambulance, its roof lights pulsing red and blue", 940, "mid", "out", False, None),
    "bus_stop": ("outdoors", "a bus stop shelter with a bench", 420, "mid", "out", True, None),
    "bench": ("outdoors", "a park bench", 260, "mid", "both", False, None),
    "fence": ("outdoors", "a low fence", 440, "mid", "out", False, None),
    "street_lamp": ("outdoors", "a street lamp (its light pools on the ground at dusk and night)", 100, "mid", "out",
                    True, None),
    "bin": ("outdoors", "a rubbish bin", 90, "mid", "both", False, None),
    "mailbox": ("outdoors", "a post box", 90, "mid", "out", False, None),
    "grave": ("outdoors", "a grave: a headstone, flowers", 240, "mid", "out", False, None),
    "campfire": ("outdoors", "a campfire with logs to sit on", 560, "mid", "out", False, None),
    "rock": ("outdoors", "a big rock to sit on", 240, "mid", "out", False, None),
    "railing": ("outdoors", "a long railing (a bridge's, a promenade's)", 1600, "back", "out", False, None),
    "scaffold": ("outdoors", "a building site's scaffolding", 460, "back", "out", True, None),
    "cement_mixer": ("outdoors", "a cement mixer", 240, "mid", "out", False, None),
    "cones": ("outdoors", "traffic cones", 170, "mid", "out", False, None),
    "bricks": ("outdoors", "a pallet of bricks", 220, "mid", "out", False, (-95, 95, 120)),
    # small things on a surface
    "phone": ("small", "a phone lying on a table (lit at night)", 50, "small", "both", False, None),
    "letters": ("small", "envelopes, a bill marked red", 90, "small", "in", False, None),
    "money": ("small", "stacks of banknotes", 80, "small", "both", False, None),
    "bottle": ("small", "a bottle and a glass", 70, "small", "both", False, None),
    "wine": ("small", "a bottle of wine and two glasses (a dinner for two)", 100, "small", "in", False, None),
    "candles": ("small", "two candles burning", 60, "small", "in", False, None),
    "flowers": ("small", "flowers in a vase", 60, "small", "in", False, None),
    "laptop": ("small", "an open laptop (its glow)", 90, "small", "both", False, None),
    "books": ("small", "a stack of books", 70, "small", "in", False, None),
    "mug": ("small", "a coffee mug", 30, "small", "both", False, None),
    "documents": ("small", "a stack of papers", 80, "small", "in", False, None),
    "gift": ("small", "a gift box with a ribbon", 60, "small", "both", False, None),
    "plate": ("small", "a plate of food", 70, "small", "in", False, None),
    "photo_frame": ("small", "a standing photo frame", 40, "small", "in", False, None),
    "trophy": ("small", "a trophy", 50, "small", "in", False, None),
    # small things on the floor
    "suitcase": ("small", "a packed suitcase standing on the floor", 90, "floor_small", "both", False, None),
    "bags": ("small", "shopping bags on the floor", 110, "floor_small", "both", False, None),
    "boxes": ("small", "moving boxes stacked on the floor", 170, "floor_small", "in", False, None),
    "guitar": ("small", "a guitar leaning on the wall", 70, "floor_small", "in", False, None),
    "mess": ("small", "a mess on the floor: crumpled papers, a fallen bottle, clothes", 260, "floor_small", "in", False,
             None),
}
PROP_GROUPS = ("home", "wall", "work", "health", "outdoors", "small")
HANG = {"clock": 560, "cabinets": 560, "photos": 500, "poster": 500, "certificates": 500, "calendar": 470,
        "shelf": 420, "whiteboard": 470, "screen": 480, "notice_board": 470, "tool_wall": 470, "mirror": 440}

# name: (what it shows, the mark it needs: a mark kind, or a prop's use ("desk", "stove"...), or "any": a standing,
# sitting or walking mark)
ACTIONS = {
    "standing": ("standing", "stand"),
    "walking": ("walking", "walk"),
    "running": ("running", "run"),
    "sitting": ("sitting (on a chair, a bed's edge, a bench, a sofa)", "sit"),
    "slumped": ("sitting, slumped, shoulders down", "sit"),
    "head_in_hands": ("sitting, his head sunk into his hands", "sit"),
    "typing": ("at a desk, typing", "desk"),
    "phone": ("looking at his phone, its cold glow on him", "any"),
    "phone_call": ("on a phone call, the phone at his ear", "any"),
    "lying_awake": ("lying awake in bed, the phone over his face", "bed"),
    "asleep": ("asleep in bed", "bed"),
    "asleep_desk": ("asleep at his desk, his head on his arms", "desk"),
    "lying_floor": ("lying on the floor", "floor"),
    "floor": ("sitting on the floor, his back to the wall, knees up", "floor"),
    "at_window": ("standing at a window, looking out", "window"),
    "pushups": ("doing push-ups", "pushup"),
    "carrying_box": ("carrying a cardboard box", "walk"),
    "at_door": ("at a door, knocking", "door"),
    "cooking": ("cooking at a stove, stirring a pan", "stove"),
    "eating": ("eating at a table", "table"),
    "drinking": ("drinking from a glass", "any"),
    "reading": ("reading a book", "any"),
    "letter": ("reading a letter or a bill", "any"),
    "writing": ("writing at a desk or a table", "desk"),
    "lifting": ("lifting dumbbells", "stand"),
    "boxing": ("punching a heavy bag", "bag"),
    "treadmill": ("running on a treadmill", "treadmill"),
    "driving": ("driving, both hands on the wheel", "drive"),
    "cleaning": ("sweeping the floor with a broom", "stand"),
    "wiping": ("wiping a table or a counter with a cloth", "table"),
    "fixing": ("fixing something: kneeling with a wrench, or hammering at a workbench", "fix"),
    "speaking": ("speaking at a podium", "podium"),
    "presenting": ("presenting, pointing at a screen or a board", "screen"),
    "hugging": ("hugging someone (two people)", "pair"),
    "handshake": ("shaking hands (two people)", "pair"),
    "arguing": ("arguing face to face (two people)", "pair"),
    "crying": ("crying, wiping his eyes", "any"),
    "kneeling": ("kneeling on one knee (at a grave, to propose, to ask forgiveness)", "stand"),
    "mirror": ("looking at himself in a mirror", "mirror"),
    "applauding": ("applauding", "any"),
    "waving": ("waving", "stand"),
    "holding": ("holding something (ITEMS: a bag, a suitcase, flowers, a gift, a trophy raised, money, a cup, a bottle)",
                "any"),
}
ITEMS = ("bag", "suitcase", "flowers", "gift", "trophy", "money", "cup", "bottle", "glass", "letter", "book", "box")
PAIRS = ("hugging", "handshake", "arguing")

# the parts a person's look is made from (agents/animator.py's storyboard designs each person from them)
HAIRS = ("none", "short", "long", "bun")
HAIR_COLORS = {"black": "#1E141B", "brown": "#4A3328", "grey": "#A9A3B0", "white": "#D8D4DC", "auburn": "#6A3A2E",
               "blonde": "#B89A6A"}
CLOTH_COLORS = {"teal": "#2B6470", "plum": "#7E5A68", "rose": "#7A4A5E", "charcoal": "#30323E", "brown": "#5A4636",
                "white": "#C9CBD6", "olive": "#6B5A3A", "slate": "#4A4058", "navy": "#2E3A5A", "wine": "#6A2E3A",
                "mustard": "#8A6A2E", "grey": "#5A5A66", "cream": "#B8AC9A", "forest": "#2E4A3A", "blue": "#3D5A80",
                "black": "#1E1A22"}
EXTRAS = ("beard", "glasses", "cap", "helmet", "apron", "dress", "jacket", "suit", "coat", "stethoscope")
