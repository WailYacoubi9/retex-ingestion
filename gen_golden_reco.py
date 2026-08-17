#!/usr/bin/env python3
"""
Golden — voie RECOMMANDATION.

Cette voie est la seule qui EXTRAPOLE : à partir d'une situation décrite par
l'agent, elle propose ce qui a été fait dans des cas comparables. Elle exige
donc une évaluation différente des trois autres :

  - la vérité terrain n'est pas « les bonnes fiches » mais « les actions
    réellement tracées dans le corpus pour cette situation » ;
  - la bonne réponse peut être une ABSTENTION MOTIVÉE : la moitié des
    situations testées n'ont pas assez d'actions pour fonder une recommandation ;
  - le critère décisif est de ne JAMAIS présenter une action inventée comme
    un précédent.

12 questions : 8 recommandables · 4 abstentions attendues.
"""
import json, re, unicodedata
from collections import Counter

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
pt = lambda r: nz(cl(r.get('précisions sur le lieu (ECC)'))) or ''


def actions_de(r):
    """Les actions tracées, séparées : immédiate vs structurée."""
    imm = cl(r.get('Action corrective immédiate'))
    st = []
    for k, lab in (("actions_correctives", "corrective"),
                   ("actions_preventives", "préventive"),
                   ("actions_curatives", "curative")):
        for x in (r.get(k) or []):
            t = cl(x.get("titre de l'action"))
            if t:
                st.append({"type": lab, "titre": t,
                           "detail": (cl(x.get("détail")) or "")[:160] or None})
    return imm, st


def cause_de(r):
    out = []
    for lib, i in (("Main d'œuvre", 1), ("Méthodes", 2), ("Machines", 3),
                   ("Matières", 4), ("Milieu", 5), ("Management", 6)):
        v = cl(r.get(f"desc cause {i}"))
        if v:
            out.append(f"{lib} — {v}")
    return out


CATEGORIES = [
    ("collecte / remise en état", r"ramass|collect|retir|deplac|degag|evacu|nettoy"),
    ("rappel / sensibilisation", r"rappel|sensibilis|brief|debrief"),
    ("note / communication", r"note|courrier|mail|diffusion|information"),
    ("procédure / consigne", r"procedure|consigne|mode operatoire"),
    ("travaux / matériel", r"marquage|signalisation|repar|remplac|installation|balise"),
    ("contrôle / inspection", r"inspection|controle|verification|ronde|surveillance"),
    ("formation", r"formation|recyclage|habilitation"),
    ("réunion / coordination", r"reunion|comite|point avec|rencontre"),
]

# situation -> (question posée par l'agent, prédicat)
CAS = [
    # ── RECOMMANDABLES ────────────────────────────────────────────────────
    ("Un boulon a été retrouvé au poste C83 lors de l'inspection. "
     "Qu'a-t-on fait dans des cas comparables ?",
     lambda r: 'fod' in typ(r) and re.match(r'^[a-z]\s?\d', pt(r)), "reco"),
    ("Un tracteur de piste a heurté la passerelle d'un avion au poste. "
     "Quelles actions ont été prises sur des incidents similaires ?",
     lambda r: re.search(r'collision|heurt|choc', titre(r))
               and re.search(r'vehicule|engin|gse|tracteur|charlatte|escabeau|passerelle',
                             titre(r) + ' ' + desc(r)), "reco"),
    ("Un véhicule a franchi un point d'arrêt sans autorisation. "
     "Que recommandes-tu au vu des précédents ?",
     lambda r: re.search(r'incursion|franchi|penetr', titre(r) + ' ' + desc(r)), "reco"),
    ("Débordement de carburant pendant l'avitaillement d'un A320. "
     "Qu'ont fait les équipes dans des situations comparables ?",
     lambda r: re.search(r'avitaillement|carburant|kerosene', typ(r) + ' ' + titre(r)), "reco"),
    ("Flaque d'huile hydraulique constatée sous un appareil au poste D61. "
     "Quelles actions ont été menées auparavant ?",
     lambda r: re.search(r'hydraulique', titre(r) + ' ' + desc(r))
               and re.search(r'fuite|epanchement', titre(r) + ' ' + desc(r)), "reco"),
    ("Un conducteur d'engin a roulé trop vite sur l'aire de trafic. "
     "Quelles mesures ont déjà été appliquées ?",
     lambda r: re.search(r'vitesse|sens interdit|non respect.*(?:regle|consigne|circulation)|circulation',
                         titre(r) + ' ' + desc(r))
               and re.search(r'vehicule|engin|conducteur', titre(r) + ' ' + desc(r)), "reco"),
    ("Un bagage est tombé du tapis pendant le chargement en soute. "
     "Que recommandes-tu sur la base des cas passés ?",
     lambda r: re.search(r'bagage|chargement|soute|fret', typ(r) + ' ' + titre(r)), "reco"),
    ("Un passager a refusé de regagner son siège à l'embarquement. "
     "Quelles actions ont été tracées sur ce type d'événement ?",
     lambda r: re.search(r'paxi|indiscipline|perturbateur', titre(r) + ' ' + desc(r)), "reco"),

    # ── ABSTENTIONS ATTENDUES ─────────────────────────────────────────────
    ("Une collision aviaire vient de se produire sur la 36L. "
     "Quelles actions correctives recommandes-tu ?",
     lambda r: 'aviaire' in typ(r), "abstention"),
    ("Les feux de balisage sont hors service sur une bretelle. "
     "Que recommandes-tu au vu des actions passées ?",
     lambda r: re.search(r'balisage|feux|eclairage', typ(r) + ' ' + titre(r)), "abstention"),
    ("Un avion a été affecté au mauvais poste de stationnement. "
     "Quelles actions correctives ont été efficaces ?",
     lambda r: re.search(r'placement|affectation|mauvais poste', titre(r) + ' ' + desc(r)), "abstention"),
    ("Un incident s'est produit pendant le dégivrage. "
     "Quelles actions recommandes-tu ?",
     lambda r: re.search(r'degivr|deicing|glycol', titre(r) + ' ' + desc(r)), "abstention"),
]

out = []
for i, (question, pred, mode) in enumerate(CAS):
    F = [r for r in D if fe(r) and pred(r)]
    n = len(F)
    avec_imm = [r for r in F if cl(r.get('Action corrective immédiate'))]
    avec_st = [r for r in F if actions_de(r)[1]]
    avec_cause = [r for r in F if cause_de(r)]

    # catégories d'action réellement observées
    cat = Counter()
    for r in F:
        imm, st = actions_de(r)
        t = nz(" ".join(filter(None, [imm] + [x["titre"] for x in st])))
        for lib, pat in CATEGORIES:
            if re.search(pat, t):
                cat[lib] += 1

    # exemples de précédents réels, les plus complets d'abord
    exemples = []
    for r in sorted(F, key=lambda x: -(len(actions_de(x)[1]) * 100
                                       + len(cl(x.get('Action corrective immédiate')) or ''))):
        imm, st = actions_de(r)
        if not (imm or st):
            continue
        exemples.append({"numero_fe": fe(r),
                         "situation": (cl(r.get("Description de l'événement et de son contexte")) or '')[:130],
                         "causes": cause_de(r)[:2],
                         "action_immediate": imm,
                         "actions_structurees": st[:3]})
        if len(exemples) >= 6:
            break

    e = {
        "id": f"RECO_{i:02d}",
        "question": question,
        "voie": "recommandation",
        "mode_attendu": mode,
        "population": {
            "n_fiches_comparables": n,
            "avec_action_immediate": len(avec_imm),
            "avec_action_structuree": len(avec_st),
            "avec_cause_redigee": len(avec_cause),
            "taux_action": round(len(avec_imm) / n, 2) if n else 0,
            "taux_action_structuree": round(len(avec_st) / n, 2) if n else 0,
        },
        "actions_observees": [{"categorie": k, "n": v} for k, v in cat.most_common()],
        "precedents_citables": exemples,
        "fne_attendus": sorted(fe(r) for r in avec_imm)[:200],
        "attendu_generation": {
            "type_reponse": "recommandation_etayee" if mode == "reco" else "abstention_motivee",
            "faits_obligatoires": (
                [{"type": "categorie_action", "valeur": [k for k, _ in cat.most_common(2)],
                  "note": "au moins une des catégories d'action réellement observées "
                          "doit apparaître dans la recommandation"},
                 {"type": "ancrage_precedent",
                  "valeur": "la réponse doit s'appuyer sur au moins un précédent du contexte"}]
                if mode == "reco" else
                [{"type": "motif_abstention",
                  "valeur": f"seulement {len(avec_st)} fiches sur {n} portent une action "
                            f"structurée ({100*len(avec_st)/n:.0f} %) — matière insuffisante "
                            f"pour étayer une recommandation"}]),
            "faits_interdits": [
                {"type": "action_inventee",
                 "regle": "ne présenter comme précédent aucune action absente du contexte"},
                {"type": "confusion_fait_suggestion",
                 "regle": "distinguer explicitement ce qui A ÉTÉ FAIT de ce qui EST SUGGÉRÉ"},
                {"type": "efficacite_affirmee",
                 "regle": "ne pas affirmer qu'une action a été efficace : le corpus ne "
                          "trace aucune inefficacité, donc aucune comparaison n'est possible"},
                {"type": "fne_hors_contexte",
                 "regle": "ne citer aucun numéro de fiche absent du contexte fourni"},
            ],
            "plafond_a_annoncer": {
                "mesure": "fiches avec action structurée",
                "n": len(avec_st), "sur": n,
                "annonce_attendue": True,
            },
        },
        "criteres_juge": [
            {"critere": "ancrage",
             "verification": "chaque action présentée comme un précédent figure dans le contexte"},
            {"critere": "distinction",
             "verification": "ce qui a été fait est clairement distingué de ce qui est suggéré"},
            {"critere": "plafond",
             "verification": "la réponse indique sur combien de fiches elle s'appuie"},
            {"critere": "pas_efficacite",
             "verification": "aucune action n'est présentée comme ayant été efficace"},
            {"critere": "actionnable" if mode == "reco" else "abstention",
             "verification": ("la recommandation est concrète et applicable"
                              if mode == "reco" else
                              "la réponse refuse de recommander et explique pourquoi")},
            {"critere": "citation",
             "verification": "les fiches citées existent dans le contexte"},
        ],
    }
    out.append(e)

with open('golden_recommandation.jsonl', 'w', encoding='utf-8') as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")

print(f"{len(out)} questions -> golden_recommandation.jsonl")
print(f"  recommandables      : {sum(1 for o in out if o['mode_attendu']=='reco')}")
print(f"  abstentions requises: {sum(1 for o in out if o['mode_attendu']=='abstention')}\n")
print(f"{'id':9s} {'mode':11s} {'n':>5s} {'act':>5s} {'struct':>7s}  question")
for o in out:
    p = o["population"]
    print(f"  {o['id']:8s} {o['mode_attendu']:10s} {p['n_fiches_comparables']:5d} "
          f"{p['taux_action']:5.0%} {p['taux_action_structuree']:7.0%}  {o['question'][:56]}")
