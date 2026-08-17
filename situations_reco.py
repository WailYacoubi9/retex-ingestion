import json, re, unicodedata
from collections import Counter, defaultdict

D = json.load(open('/mnt/user-data/uploads/incidents_avec_actions.json'))

def cl(v):
    if v is None:
        return None
    s = re.sub(r'\s+', ' ', str(v)).strip()
    return s if s and s.lower() not in {'0', '-', 'n/a', 'na', 'ras', 'nil'} else None

def nz(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()

fe = lambda r: cl(r.get('Num F.E.'))
typ = lambda r: nz(cl(r.get("type d'événement (ECC)")))
titre = lambda r: nz(cl(r.get('titre')))
desc = lambda r: nz(cl(r.get("Description de l'événement et de son contexte")))

def action_txt(r):
    a = [cl(r.get('Action corrective immédiate'))]
    a += [cl(x.get("titre de l'action")) for k in
          ("actions_correctives", "actions_preventives", "actions_curatives")
          for x in (r.get(k) or [])]
    a += [cl(x.get("détail")) for k in
          ("actions_correctives", "actions_preventives", "actions_curatives")
          for x in (r.get(k) or [])]
    return " ".join(filter(None, a))

def a_struct(r):
    return any(r.get(k) for k in ("actions_correctives", "actions_preventives", "actions_curatives"))

def cause_txt(r):
    return " ".join(filter(None, [cl(r.get(f"desc cause {i}")) for i in range(1, 7)]))

# Une recommandation est fondée si la situation a :
#   - assez de précédents  (>= 8 fiches)
#   - des actions TRACÉES  (>= 40 % avec action texte)
#   - de préférence des actions structurées
SITUATIONS = [
    ("FOD sur un poste de stationnement",
     lambda r: 'fod' in typ(r) and re.search(r'^[a-z]\s?\d', nz(cl(r.get('précisions sur le lieu (ECC)'))) or '')),
    ("FOD sur piste",
     lambda r: 'fod' in typ(r) and re.search(r'\b(1[78]|3[56])\s?[lr]\b', nz(cl(r.get('précisions sur le lieu (ECC)'))) or '')),
    ("refus de priorité pendant un repoussage",
     lambda r: re.search(r'priorite', titre(r) + ' ' + desc(r)) and re.search(r'repouss|push', titre(r) + ' ' + desc(r))),
    ("matériel de piste mal stationné",
     lambda r: re.search(r'materiel|gse|engin', titre(r) + ' ' + desc(r)) and re.search(r'genant|mal stationne|stationnement non|encombr', titre(r) + ' ' + desc(r))),
    ("collision entre un engin et un aéronef",
     lambda r: re.search(r'collision|heurt|choc', titre(r)) and re.search(r'vehicule|engin|gse|tracteur|charlatte|escabeau|passerelle', titre(r) + ' ' + desc(r))),
    ("incursion sur piste ou voie de circulation",
     lambda r: re.search(r'incursion|franchi|penetr', titre(r) + ' ' + desc(r))),
    ("problème lors de l'avitaillement",
     lambda r: re.search(r'avitaillement|carburant|kerosene', typ(r) + ' ' + titre(r))),
    ("fuite hydraulique au poste",
     lambda r: re.search(r'hydraulique', titre(r) + ' ' + desc(r)) and re.search(r'fuite|epanchement', titre(r) + ' ' + desc(r))),
    ("passager indiscipliné",
     lambda r: re.search(r'paxi|indiscipline|perturbateur', titre(r) + ' ' + desc(r))),
    ("défaillance du balisage lumineux",
     lambda r: re.search(r'balisage|feux|eclairage', typ(r) + ' ' + titre(r))),
    ("problème lors du chargement des bagages",
     lambda r: re.search(r'bagage|chargement|soute|fret', typ(r) + ' ' + titre(r))),
    ("collision aviaire",
     lambda r: 'aviaire' in typ(r)),
    ("erreur de placement ou d'affectation d'avion",
     lambda r: re.search(r'placement|affectation|mauvais poste', titre(r) + ' ' + desc(r))),
    ("dégivrage",
     lambda r: re.search(r'degivr|deicing|glycol', titre(r) + ' ' + desc(r))),
    ("véhicule circulant sans respecter les règles sur l'aire",
     lambda r: re.search(r'vitesse|sens interdit|non respect.*(?:regle|consigne|circulation)|circulation', titre(r) + ' ' + desc(r))
               and re.search(r'vehicule|engin|conducteur', titre(r) + ' ' + desc(r))),
]

print(f"{'situation':46s} {'n':>5s} {'act.txt':>8s} {'act.str':>8s} {'cause':>7s}  verdict")
print("-" * 92)
retenues = []
for lib, pred in SITUATIONS:
    F = [r for r in D if fe(r) and pred(r)]
    n = len(F)
    if not n:
        continue
    at = sum(1 for r in F if cl(r.get('Action corrective immédiate')))
    st = sum(1 for r in F if a_struct(r))
    ca = sum(1 for r in F if cause_txt(r))
    ok = n >= 8 and at / n >= 0.35
    verdict = "RECOMMANDABLE" if ok and st >= 3 else ("limite" if ok else "ABSTENTION attendue")
    print(f"  {lib[:44]:46s} {n:5d} {100*at/n:7.0f}% {100*st/n:7.0f}% {100*ca/n:6.0f}%  {verdict}")
    retenues.append((lib, F, at, st, ca, verdict))

print("\n\n=== Les actions réellement tracées, par situation retenue ===")
for lib, F, at, st, ca, verdict in retenues:
    if verdict == "ABSTENTION attendue":
        continue
    acts = Counter()
    for r in F:
        t = nz(action_txt(r))
        for cat, pat in [("rappel/sensibilisation", r"rappel|sensibilis|brief|debrief"),
                         ("note/communication", r"note|courrier|mail|diffusion|information"),
                         ("procédure/consigne", r"procedure|consigne|mode operatoire|regle"),
                         ("travaux/matériel", r"marquage|signalisation|repar|remplac|installation|balise"),
                         ("contrôle/inspection", r"inspection|controle|verification|ronde|surveillance"),
                         ("formation", r"formation|recyclage|habilitation"),
                         ("réunion/coordination", r"reunion|comite|point avec|rencontre"),
                         ("collecte/remise en état", r"ramass|collect|retir|deplac|degag|evacu|nettoy")]:
            if re.search(pat, t):
                acts[cat] += 1
    top = ", ".join(f"{k} ({v})" for k, v in acts.most_common(4))
    print(f"  ▸ {lib} — {len(F)} fiches")
    print(f"      {top}")
