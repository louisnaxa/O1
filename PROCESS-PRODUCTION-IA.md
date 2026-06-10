# Process de production par agent IA — le système qui rend la production fiable par conception

> Document fondateur. Ce n'est PAS la spec d'un orchestrateur technique — c'est le PROCESS dont
> tout orchestrateur ne sera que l'exécution. Il encode la méthode qui a fait réussir P1, en
> garantie structurelle plutôt qu'en vigilance humaine.
>
> Principe : un agent IA est puissant mais faillible de façons PRÉVISIBLES. La fiabilité ne vient
> pas d'un meilleur agent — elle vient d'un PROCESS qui rend ses modes de défaillance impossibles
> à laisser passer. L'humain ne doit intervenir que là où le jugement est irremplaçable, jamais
> pour rattraper une défaillance que le système aurait dû attraper seul.
>
> Réutilisable tel quel pour l'orchestrateur ET pour la plateforme d'échange (le vrai projet).

---

## 0. Le but, en une phrase

Rendre la production par agent IA **frictionless pour l'humain et fiable par conception** : l'humain
donne une intention, le système produit du travail prouvé, et les défaillances connues des agents
sont neutralisées structurellement — pas par la vigilance de l'humain, qui est l'étroitesse qu'on
veut supprimer.

---

## 1. Les quatre rôles (séparation stricte des pouvoirs)

| Rôle | Pouvoir | Ne peut PAS |
|---|---|---|
| **Humain** | Donne l'intention. Tranche le jugement irremplaçable (money-path, stratégie, produit, juridique). | Être requis pour rattraper une défaillance technique attrapable par le système. |
| **Agent** | Lit le code réel, conçoit, code, exécute les tests. | S'auto-valider. Déclarer un jalon franchi. Décider seul sur le money-path. |
| **Superviseur** | Juge le sens, la méthode, le risque. Cadre, valide ou refuse le travail de l'agent. | Coder. Voir le repo directement (il raisonne sur ce que l'agent rapporte — angle mort à compenser, cf. §6). |
| **Orchestrateur** | Route, vérifie mécaniquement (CI réel), applique les garde-fous, décide quand réveiller l'humain. | Avoir un jugement propre. Il EXÉCUTE le process, il ne l'interprète pas. |

Règle d'or de séparation : **celui qui produit ne valide jamais son propre travail.** L'agent
produit, le superviseur juge, l'orchestrateur vérifie le fait brut (CI), l'humain tranche le jugement.

---

## 2. L'ordre canonique de toute tâche (le cycle invariant)

Toute unité de travail, sans exception, suit cet ordre. Le process ne permet pas de sauter une étape.

```
INTENTION (humain ou plan)
  → CADRAGE (superviseur : périmètre + inventaire des chemins existants touchés + preuve attendue)
  → LOCALISATION (agent : lit le code réel, confirme où ça s'attache, AVANT de coder)
  → VALIDATION DU CADRAGE (superviseur : l'architecture est-elle juste ? le périmètre borné ?)
  → CODE (agent : implémente le périmètre validé, rien de plus)
  → PREUVE (agent : tests qui prouvent le passage ET le refus, contre infra RÉELLE)
  → VÉRIFICATION DU FAIT (orchestrateur : statut CI RÉEL via API, jamais la parole de l'agent)
  → JUGEMENT (superviseur : la preuve prouve-t-elle vraiment ce qu'elle prétend ?)
  → [si money-path] OK HUMAIN (l'humain valide l'inscription)
  → INSCRIPTION (le repo enregistre le jalon franchi — source de vérité unique)
```

Aucune étape n'est optionnelle. Le « code » ne peut pas précéder la « localisation ». L'« inscription »
ne peut pas précéder le « jugement ». C'est l'ordre qui garantit, pas la bonne volonté de l'agent.

---

## 3. Les invariants garantis par construction (ce que le système rend IMPOSSIBLE)

Ce sont les promesses non négociables. Le process est conçu pour qu'aucune ne puisse être violée.

1. **Aucun faux vert.** Un jalon n'avance jamais sur la parole de l'agent. Le statut CI est lu à la
   source (API du système de CI). « En queue » et « in_progress » ne sont pas « vert ».
2. **Aucune preuve contre maquette sur le money-path.** Ce qui touche l'argent est prouvé contre
   l'infra réelle (vraie base, vrai registre), jamais un substitut (pas de H2 pour PostgreSQL).
3. **Le refus est prouvé, pas seulement le passage.** Sur toute frontière de sécurité ou d'argent,
   le test prouve que le cas interdit est REJETÉ — pas seulement que le cas permis fonctionne.
4. **Aucun jalon money-path inscrit sans OK humain.** Même tout vert, l'argent réel exige le geste
   humain. Incompressible, mais réduit à dix secondes.
5. **Aucune dérive silencieuse à la frontière neuf/ancien.** Tout cadrage exige l'inventaire des
   chemins existants touchés ; toute fonction de contrôle est prouvée CÂBLÉE, pas seulement correcte.
6. **Le standard prime sur l'infra ; le custom se justifie.** Sur la plomberie (réseau, stockage,
   auth, orchestration), le standard éprouvé est le défaut ; toute déviation custom doit avoir une
   raison technique nommée, pas « plus simple à écrire ».
7. **Le repo est la seule source de vérité.** Si deux artefacts divergent, le code tranche. Rien
   n'existe tant que non inscrit. La doc raconte toujours la même chose que le code.
8. **Une brique à la fois, finie et prouvée avant la suivante.** Pas d'inscription du supposé. On
   n'inscrit que le prouvé.

---

## 4. La table des défaillances → garanties (le cœur de la fiabilité)

Chaque mode de défaillance RÉEL observé, et le mécanisme structurel qui le neutralise.

| Défaillance de l'agent | Cause | Mécanisme structurel qui la neutralise |
|---|---|---|
| « C'est vert » alors que le job est en queue | L'agent croit/optimiste | Orchestrateur lit le CI réel à la source. Ne passe pas tant que ≠ vert. |
| Teste contre H2 au lieu de PostgreSQL | Plus simple localement | Cadrage money-path EXIGE l'infra réelle. Superviseur refuse une preuve sur maquette. |
| Prouve le chemin heureux, pas le refus | L'agent teste ce qui marche | Cadrage EXIGE le test de refus comme condition de la brique. |
| Fonction correcte mais pas câblée partout | Optimise son périmètre, pas la frontière | Cadrage EXIGE l'inventaire des chemins + test de câblage (preuve que c'est branché). |
| Choisit le plus simple à écrire (custom infra) | Minimise son effort immédiat | Question imposée au cadrage : « pourquoi pas le standard ? ». Custom = raison nommée. |
| Dérive du périmètre / sur-construit | Pas de borne claire | Cadrage borne explicitement quoi faire ET quoi NE pas faire. Superviseur refuse le hors-périmètre. |
| Oublie un chemin d'accès (porte dérobée) | Vue locale de la tâche | Inventaire des chemins obligatoire avant code. Fail-closed par défaut. |
| Se rassure sur du faux (« ça compile = ça marche ») | Confond exécution et preuve | « Prouver pas prétendre » : seule la preuve contre le réel compte, jamais la compilation. |
| Rumine sans produire | Boucle interne | Garde-fou anti-dérive : limite de tours sans convergence → réveil humain. |
| Inscrit le supposé comme décidé | Anticipe au lieu de constater | On n'inscrit que le prouvé. La doc suit le réel, ne le précède pas. |

Cette table EST la spécification de l'outil. Tout orchestrateur doit implémenter une garantie pour
chaque ligne. Une ligne sans garantie = un trou de fiabilité connu.

---

## 5. Les points de réveil humain (et eux seuls)

L'humain est réveillé (ping) UNIQUEMENT sur :
- **Money-path qui se ferme** : inscription d'une brique touchant l'argent. → validation.
- **Architecture structurante** : choix qui change la forme d'un module / une surface d'attaque.
- **Décision produit** : ce que seul l'humain a l'information pour trancher.
- **Drapeau juridique** : tout ce qui touche conformité/qualification/collecte.
- **Blocage réel** : CI rouge répété, dérive, désaccord agent↔superviseur non résolu.

Pour TOUT le reste, le système avance seul. Le but : l'humain ne voit que les décisions dignes de
son jugement, jamais la plomberie.

---

## 6. L'angle mort à compenser (honnêteté sur les limites)

Le superviseur et l'agent sont tous deux des instances du même type de modèle. Ils PARTAGENT des
biais. Un défaut que l'agent ne voit pas, le superviseur peut ne pas le voir non plus — c'est
l'angle mort structurel d'un système où le juge et le produit sont de même nature.

Compensations conçues dans le process :
- **La vérification mécanique est non-IA.** Le CI réel, les contraintes de base, les tests : ce sont
  des faits bruts, pas des jugements d'IA. Ils ne partagent pas les biais des modèles. C'est la
  couche de vérité qui ne ment pas, sur laquelle tout le reste s'appuie.
- **Le refus prouvé est un fait, pas une opinion.** Un test de rejet qui passe est une vérité
  mécanique, pas un jugement partagé.
- **L'humain reste le tiers de nature différente** sur les décisions à enjeu. Sa rareté
  d'intervention est compensée par le fait qu'il est réveillé exactement aux bons points.
- **Diversité possible** : superviseur et agent peuvent être des modèles différents (familles
  différentes) pour réduire les biais partagés. À considérer si un mode de défaillance échappe
  systématiquement aux deux.

---

## 7. De ce process à l'outil (ordre de dérivation)

L'outil se DÉRIVE de ce process, il ne le précède pas.

1. Ce document (le process) est la spécification fondatrice.
2. L'orchestrateur technique implémente §2 (l'ordre canonique), §3 (les invariants), §4 (une
   garantie par défaillance), §5 (les points de réveil).
3. Les choix techniques (moteur d'orchestration, persistance, observabilité du coût) sont des
   MOYENS d'exécuter §2-§5. Ils se choisissent pour leur capacité à porter ces garanties, pas
   pour eux-mêmes. Critères : exécution durable/reprise (la boucle survit aux interruptions),
   human-in-the-loop natif (les réveils du §5), observabilité du coût (piloter la dépense).
4. Le custom ne se construit que sur le DELTA que le standard ne couvre pas (ex. vérification CI
   indépendante + réveil ciblé money-path) — jamais l'inverse.

---

## 8. Pourquoi cet actif vaut au-delà de l'orchestrateur

Ce process ne dépend d'aucun projet. Il encode comment produire du logiciel fiable PAR AGENT, quel
que soit le domaine. Il sert :
- maintenant, à construire l'orchestrateur lui-même (premier client du process) ;
- ensuite, à produire la plateforme d'échange (le projet à valeur économique, fintech régulée, où
  la fiabilité par conception n'est pas un confort mais une nécessité).

C'est le garant de la réussite technique que tu cherchais : pas un outil, un PROCESS, dont l'outil
n'est que l'exécution, et qui rend la fiabilité indépendante de la vigilance d'un cerveau humain
faillible — en la rendant structurelle.
