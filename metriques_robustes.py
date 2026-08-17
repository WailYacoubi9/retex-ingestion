"""Métriques robustes à une vérité terrain incomplète.

POURQUOI — notre vérité terrain vient d'un prédicat (une regex). Il produit des faux
négatifs démontrés : sur « cause : agent nouvellement arrivé », une fiche dit « l'agent
mis en cause est un NOVICE en cours de formation ». Sémantiquement juste, absent de la
regex, donc compté faux. Le système est pénalisé pour avoir eu raison.

MODÈLE RETENU — on ne traite PAS le prédicat comme une vérité complète :
  prédicat-positif -> pertinent (fiable : la regex ne produit pas de faux positifs ici,
                      elle exige la présence littérale du motif)
  prédicat-négatif -> INCERTAIN, pas « non pertinent »
C'est ce renversement qui rend bpref et le résidu RBP applicables.

TROIS ESTIMATEURS, du plus pessimiste au plus utile :

  1. bpref            — n'utilise que les documents jugés, ignore les incertains.
  2. RBP + résidu     — renvoie un INTERVALLE [borne basse, borne haute] plutôt qu'un point.
                        Borne haute = « et si tous les incertains étaient pertinents ». Cet
                        encadrement est honnête mais large ; il sert de garde-fou, pas de
                        mesure.
  3. précision corrigée par échantillonnage — LA méthode exploitable. On juge un
                        ÉCHANTILLON des incertains réellement remontés, on en tire le taux
                        de faux négatifs, et on corrige. Coût : ~100 jugements, contre
                        ~1 500 pour un pooling complet.

Aucune de ces trois ne dit si l'assistant RÉPOND bien — c'est l'affaire de resultats_generation.md.
"""
import json
import math
import random

IN_JS = "/home/yie0070/retex-split/retex-ingestion/eval_voies.jsonl"


def bpref(pertinence, incertain, R):
    """bpref (Buckley & Voorhees, 2004), adapté : les INCERTAINS sont ignorés.

    pertinence : liste 0/1 par rang (1 = prédicat-positif)
    incertain  : liste booléenne par rang (True = prédicat-négatif, donc non concluant)
    R          : nombre total de pertinents connus pour la question

    Un pertinent est pénalisé par le nombre de NON-pertinents AVÉRÉS classés au-dessus de
    lui. Les incertains ne pénalisent pas : c'est précisément ce qui rend la mesure robuste.
    """
    if not R:
        return None
    non_pert_avant = 0
    total = 0.0
    for rel, inc in zip(pertinence, incertain):
        if inc:
            continue                      # ni pertinent ni contre-exemple : sans effet
        if rel:
            total += 1.0 - min(non_pert_avant, R) / R
        else:
            non_pert_avant += 1
    return total / R


def rbp(pertinence, incertain, p=0.8):
    """RBP (Moffat & Zobel, 2008) et son RÉSIDU.

    RBP  = (1-p) * Σ r_i * p^(i-1)      — l'utilisateur descend d'un rang avec proba p
    résidu = (1-p) * Σ_{incertains} p^(i-1)

    Retourne (borne_basse, borne_haute). L'écart entre les deux EST la mesure de notre
    ignorance : un résidu large veut dire « la vérité terrain ne tranche pas », pas
    « le système est mauvais ».
    """
    base = res = 0.0
    for i, (rel, inc) in enumerate(zip(pertinence, incertain)):
        poids = (1 - p) * (p ** i)
        if inc:
            res += poids
        elif rel:
            base += poids
    return base, base + res


def echantillon_a_juger(lignes, n=100, graine=13):
    """Les couples (question, fiche) INCERTAINS effectivement remontés, échantillonnés.

    C'est l'entrée du seul estimateur exploitable : on ne juge pas 9 191 fiches, on juge
    ~100 couples tirés au sort parmi ceux qui changent réellement le résultat.
    """
    couples = set()
    for d in lignes:
        for fe, rel in zip(d.get("fes", []), d.get("pertinence", [])):
            if not rel:                    # prédicat-négatif ET remonté = incertain utile
                couples.add((d["id"], d["question"], fe))
    couples = sorted(couples)
    random.Random(graine).shuffle(couples)
    return couples[:n], len(couples)


def precision_corrigee(prec_brute, taux_fn, k, n_incertains_moyen):
    """Précision corrigée du taux de faux négatifs estimé sur l'échantillon.

    prec_brute         : précision mesurée par le prédicat
    taux_fn            : fraction des incertains jugés en fait PERTINENTS
    n_incertains_moyen : nombre moyen d'incertains dans le top-k
    """
    return prec_brute + taux_fn * n_incertains_moyen / k


def ic_wilson(succes, n, z=1.96):
    """Intervalle de confiance de Wilson — robuste sur petits échantillons, contrairement
    à l'intervalle normal qui déborde de [0,1] quand le taux est proche de 0 ou 1."""
    if not n:
        return (0.0, 1.0)
    ph = succes / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    e = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return ((c - e) / d, (c + e) / d)


def main():
    lignes = [json.loads(l) for l in open(IN_JS, encoding="utf-8") if l.strip()]
    if "pertinence" not in (lignes[0] if lignes else {}):
        print("eval_voies.jsonl ne contient pas encore les listes classées.\n"
              "Relancer eval_voies.py (version qui persiste fes/fes_tous/pertinence).")
        return

    par_config = {}
    for d in lignes:
        pert = d["pertinence"]
        inc = [not r for r in pert]        # prédicat-négatif = incertain
        cle = (d["mode"], d["collection"])
        b = bpref(pert, inc, d["n_pertinents"])
        lo, hi = rbp(pert, inc)
        par_config.setdefault(cle, []).append((d["prec"], b, lo, hi))

    print(f"{len(lignes)} mesures\n")
    print(f"{'mode':11} {'collection':10} {'prec':>6} {'bpref':>7} {'RBP (encadrement)':>22}")
    for (mode, coll), v in sorted(par_config.items()):
        pr = sum(x[0] for x in v) / len(v)
        bs = [x[1] for x in v if x[1] is not None]
        b = sum(bs) / len(bs) if bs else 0.0
        lo = sum(x[2] for x in v) / len(v)
        hi = sum(x[3] for x in v) / len(v)
        print(f"{mode:11} {coll:10} {pr:6.0%} {b:7.0%}   [{lo:5.0%} , {hi:5.0%}]")

    ech, total = echantillon_a_juger(lignes)
    print(f"\nCouples incertains remontés : {total}. Échantillon à juger : {len(ech)}.")
    print("-> une fois jugés, precision_corrigee() + ic_wilson() donnent la précision réelle "
          "avec son intervalle.")


if __name__ == "__main__":
    main()
