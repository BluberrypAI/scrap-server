"""Reviewed form/code compatibility, not a waste-classification decision engine."""

# Code compatibility is checked only AFTER the classifier's confirmed handoff.
# Foam, PVC and fishing nets must never fall through to ordinary resin routes.
FORM_STATES = {
    "pp": {
        "scrap": "pp-scrap",
        "rigid": "pp-scrap",
        "film": "pp-scrap",
        "bale": "pp-bale",
        "shredded": "pp-shredded",
        "flake": "pp-shredded",
        "pellet": "pp-pellet",
    },
    "pe": {
        "scrap": "pe-scrap",
        "rigid": "pe-scrap",
        "film": "pe-scrap",
        "bale": "pe-bale",
        "shredded": "pe-shredded",
        "flake": "pe-shredded",
        "pellet": "pe-pellet",
    },
    "pet": {"bottle": "pet-bottle", "bale": "pet-bottle", "flake": "pet-flake"},
    "abs": {
        "scrap": "abs-scrap",
        "rigid": "abs-scrap",
        "flake": "abs-flake",
        "shredded": "abs-flake",
    },
    "ps": {
        "scrap": "ps-scrap",
        "rigid": "ps-scrap",
        "bale": "ps-bale",
        "flake": "ps-flake",
        "shredded": "ps-flake",
    },
    "san": {
        "scrap": "san-scrap",
        "rigid": "san-scrap",
        "flake": "san-flake",
        "shredded": "san-flake",
    },
    "pvc": {"wallpaper": "pvc-wallpaper", "rigid": "pvc-rigid"},
    "eps": {"foam": "eps-foam", "ingot": "eps-ingot"},
    "pa6": {"net": "pa6-net"},
    "pa66": {"flake": "pa66-flake", "shredded": "pa66-flake"},
    "pcabs": {"flake": "pcabs-flake", "shredded": "pcabs-flake"},
    "aluminium": {"can": "al-used-can"},
    "ferrous": {"scrap": "ferrous-scrap"},
}

FORM_CODES = {
    (material, form): ("51-03-01",) for material, forms in FORM_STATES.items() for form in forms
}
for _material in ("pp", "pe"):
    for _form in ("scrap", "rigid", "film", "bale"):
        FORM_CODES[_material, _form] = ("51-03-01", "51-03-07")
for _form in ("bottle", "bale"):
    FORM_CODES["pet", _form] = ("51-03-01", "51-03-07")
FORM_CODES.update(
    {
        ("pvc", "wallpaper"): ("51-03-03",),
        ("pvc", "rigid"): ("51-03-03",),
        ("eps", "ingot"): ("51-03-06",),
        ("eps", "foam"): ("51-03-06",),
        ("pa6", "net"): ("51-03-08",),
        ("aluminium", "can"): ("51-29-03",),
        ("ferrous", "scrap"): ("51-29-01",),
    }
)

LOT_STARTS = {(m, f): state for m, forms in FORM_STATES.items() for f, state in forms.items()}
FINISH_STATES = {
    "pp": {"pp-pellet", "pp-compound"},
    "pe": {"pe-pellet", "pe-compound"},
    "pet": {"pet-flake", "pet-pellet"},
    "abs": {"abs-pellet"},
    "ps": {"ps-pellet"},
    "san": {"san-pellet"},
    "pvc": {"pvc-recovered", "pvc-powder"},
    "eps": {"eps-ps-pellet"},
    "pa6": {"pa6-resin"},
    "pa66": {"pa66-compound"},
    "pcabs": {"pcabs-compound"},
    "aluminium": {"al-sheet", "al-sheet-ingot"},
    "ferrous": {"ferrous-billet"},
}
FORM_LABELS = {
    "scrap": "제조 잔재·스크랩",
    "rigid": "경질 제품·부품",
    "film": "폐필름",
    "shredded": "파쇄품",
    "flake": "플레이크",
    "pellet": "펠릿",
    "bale": "압축 베일",
    "bottle": "사용 후 PET병",
    "wallpaper": "PVC 벽지 잔재",
    "ingot": "EPS 감용 인고트",
    "net": "PA6 폐어망",
    "can": "사용 후 알루미늄 음료캔",
    "foam": "감용 전 EPS 스티로폼",
}
PLASTICS = set(FORM_STATES) - {"aluminium", "ferrous"}
