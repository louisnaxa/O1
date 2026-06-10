# Du process à l'outil — cahier de construction de l'orchestrateur

> Pont entre PROCESS-PRODUCTION-IA.md (le QUOI garantir) et le code (le COMMENT l'exécuter).
> Chaque ligne mappe une garantie du process à son implémentation. L'agent qui construit doit
> savoir, pour chaque morceau de code, QUELLE garantie du process il porte.
>
> Règle de dérivation (process §7) : l'outil exécute le process, il ne le réinvente pas. Le moteur
> standard porte les garanties ; le custom ne couvre que le delta que le standard ne fournit pas.

---

## 1. Le moteur d'exécution et pourquoi (pas « quel outil » mais « quelle garantie »)

Le process exige trois capacités d'exécution. On choisit le moyen qui les porte, pas l'inverse.

| Exigence du process | Capacité requise | Porté par |
|---|---|---|
| §2 L'ordre canonique survit aux interruptions (la boucle reprend où elle s'est arrêtée) | Exécution durable + checkpointing d'état | LangGraph (persistance d'état native, reprise mid-exécution) |
| §5 Réveils humains ciblés (pause, attente, reprise) | Human-in-the-loop natif par points d'interruption | LangGraph (interrupt points) |
| §3.1 / §4 Piloter et mesurer la dépense (crédit fini dès le 15 juin) | Observabilité du coût en tokens, par exécution | LangSmith (trace tokens/latence/état par run) |
| L'agent lit le repo réel, code, exécute les tests | Boucle d'agent avec accès fichiers + exécution | Claude Agent SDK (dans un nœud du graphe) |

Le custom ne couvre QUE le delta que ces standards ne fournissent pas :
- la **vérification CI indépendante** (lire le statut réel à la source, pas la parole de l'agent) ;
- le **réveil ciblé money-path** (la logique « quand précisément pinguer l'humain »).

---

## 2. La structure du graphe (exécution de l'ordre canonique §2)

Chaque étape de l'ordre canonique devient un nœud. Les transitions encodent l'impossibilité de
sauter une étape.

```
[intention] → [cadrage:superviseur] → [localisation:agent] → [validation_cadrage:superviseur]
   → [code:agent] → [preuve:agent] → [verif_CI:orchestrateur(non-IA)] → [jugement:superviseur]
   → {money-path ? → [interrupt:OK_humain]} → [inscription] → (boucle tâche suivante)
```

Points clés de la structure :
- Le nœud **verif_CI est non-IA** : c'est du code pur qui interroge l'API du CI. Il ne demande rien
  à l'agent. (Garantie §3.1 et §6 : la couche de vérité ne partage pas les biais des modèles.)
- L'arête **code ← validation_cadrage** : on ne peut pas atteindre `code` sans passer par la
  validation du cadrage. La structure du graphe rend la dérive impossible, pas la discipline.
- Le nœud **interrupt money-path** : point d'interruption LangGraph. Le graphe se met en pause,
  persiste son état, pingue l'humain, et attend. Reprend à la réponse. (Garantie §3.4.)
- Un échec à `verif_CI` ou `jugement` ne va pas à `inscription` — il reboucle vers `code` (ou
  `cadrage` si le problème est de conception), avec compteur (garde-fou anti-dérive).

---

## 3. Table d'implémentation : une garantie du process → un mécanisme de code

Reprend la table §4 du process. Chaque défaillance a un mécanisme, ici rendu concret.

| Garantie (process) | Implémentation concrète dans l'outil |
|---|---|
| Aucun faux vert (§3.1) | Nœud `verif_CI` : appelle l'API GitHub Actions, lit `conclusion`. `queued`/`in_progress` → attend (re-poll). `failure` → reboucle. Seul `success` passe. JAMAIS de lecture de la sortie texte de l'agent pour ce fait. |
| Pas de maquette sur money-path (§3.2) | Le cadrage (nœud superviseur) tague la tâche `money_path: true/false`. Si true, le jugement REFUSE une preuve dont les tests ne tournent pas contre l'infra réelle (vérifiable : le job CI utilise-t-il les vrais containers ?). |
| Refus prouvé (§3.3) | Le cadrage money-path/sécurité produit une liste de cas de refus attendus. Le jugement vérifie que la preuve les couvre. Pas de couverture du refus → pas d'inscription. |
| Fonction câblée, pas seulement correcte (§3.5) | Le cadrage exige un test de câblage. Le jugement vérifie sa présence avant inscription. |
| Standard > custom infra (§3.6) | Au cadrage d'une tâche infra, question imposée au superviseur : « existe-t-il un standard ? si oui, pourquoi custom ? ». Réponse loggée. Custom sans raison → reboucle. |
| Pas de dérive de périmètre (§4) | Le cadrage écrit le périmètre INCLUS et EXCLU. Le jugement compare le code produit au périmètre. Hors-périmètre → reboucle. |
| Pas de porte dérobée (§4) | Le cadrage exige l'inventaire des chemins. Le jugement vérifie que tous sont gardés ou explicitement hors-scope. |
| Prouver pas prétendre (§4) | `verif_CI` (fait mécanique) prime sur toute affirmation de l'agent. Structurel : l'agent ne peut pas faire avancer le graphe par sa parole. |
| Anti-rumination (§4) | Compteur de reboucles par tâche. Au seuil N sans passage → interrupt + ping humain (« bloqué sur X »). |
| Inscrire le prouvé, pas le supposé (§4) | Le nœud `inscription` n'est atteignable QUE depuis `jugement` réussi (+ OK humain si money-path). Pas d'autre arête vers `inscription`. |

---

## 4. Le delta custom à construire (le seul vrai code à écrire)

Tout le reste est porté par LangGraph/SDK/LangSmith. Le code spécifique à écrire :

**A. Le nœud `verif_CI` (non-IA).** Donné un commit/run, interroge l'API GitHub, retourne un fait
typé : `GREEN | RED | PENDING | infra_real: bool`. ~Petit, testable seul, déterministe.
→ C'est la PREMIÈRE brique à construire et prouver (le garant de confiance, cf. §5 ci-dessous).

**B. La logique de réveil ciblé.** Une fonction qui, donné l'état de la tâche (money_path ?
architecture ? produit ? juridique ? bloqué ?), décide `CONTINUE | PAUSE_HUMAN | STOP`. Encode §5
du process. Déterministe, testable par cas.

**C. Le canal humain (WhatsApp).** Sur `PAUSE_HUMAN`, envoie le contexte à l'humain et attend la
réponse (qui débloque l'interrupt LangGraph). Intégration standard (API WhatsApp/Twilio).

**D. L'instruction système du superviseur.** Encode le process (§1-§5) comme rôle du superviseur :
comment cadrer, quoi exiger (inventaire des chemins, refus, câblage), quand refuser, quand renvoyer
PAUSE_HUMAN. Versionnée, lecture seule pour la boucle (garantie : le système ne réécrit pas ses
propres règles).

---

## 5. Ordre de construction de l'outil (une brique à la fois, comme P1)

On applique le process À LA CONSTRUCTION du process. Méta, mais c'est le test ultime : si l'outil
ne peut pas être construit fiablement par la méthode, la méthode est fausse.

1. **Brique 1 — `verif_CI` (non-IA).** Le garant de confiance. Lit le statut CI réel. Prouvé seul :
   donné un run vert → GREEN, un run rouge → RED, un run en queue → PENDING. C'est la fondation :
   sans vérification de fait fiable, tout le reste croit l'agent sur parole. → à construire EN PREMIER.
2. **Brique 2 — la logique de réveil** (§5 encodée, déterministe, testée par cas).
3. **Brique 3 — le graphe minimal** : intention → cadrage → … → inscription, avec checkpointing,
   sur une tâche NON money-path de bout en bout (prouve que la boucle tourne et reprend).
4. **Brique 4 — l'interrupt money-path + canal WhatsApp** : prouve le réveil humain ciblé.
5. **Brique 5 — LangSmith branché** : prouve qu'on mesure le coût réel par run.

Critère de succès global : la boucle close seule une tâche non-money-path de bout en bout, pingue
correctement sur une décision money-path, reprend après une interruption simulée, et te donne une
mesure de coût réelle.

---

## 6. Ce que ce cahier garantit

Quand l'outil est construit selon ce cahier, chaque ligne de la table des défaillances (process §4)
a une implémentation qui la neutralise. Il n'y a pas de trou de fiabilité connu non couvert. Les
défaillances inconnues restent possibles (humilité §6 du process) — mais elles sont attrapées par
la couche de vérité non-IA (CI réel, tests de refus) ou par le réveil humain, jamais laissées passer
silencieusement.

C'est l'exécution du garant de réussite technique : un outil dérivé d'un process, dont chaque
morceau porte une garantie nommée, réutilisable pour la plateforme d'échange ensuite.
