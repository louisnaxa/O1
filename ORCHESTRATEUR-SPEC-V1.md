# Orchestrateur de supervision — spec de la version minimale (V1)

> But : retirer le copier-coller manuel entre l'agent (Claude Code) et le superviseur, sans
> automatiser le JUGEMENT. L'humain reste pingué (WhatsApp) aux décisions qui comptent.
> V1 = prouver l'architecture à petit coût et MESURER la consommation réelle avant d'étendre.

---

## Principe directeur (ne pas le perdre de vue)

On automatise la PLOMBERIE (passage de messages, vérification CI, relance), pas le JUGEMENT.
- Le superviseur (instance Claude via API) tranche les décisions de ROUTINE et fait avancer la boucle.
- L'humain est pingué et la boucle se met en PAUSE sur : money-path qui se ferme, architecture
  structurante, décision produit, drapeau juridique, ou blocage réel.
- Aucune brique money-path n'est inscrite « franchie » sans OK humain explicite, même si tout est vert.

---

## Les trois acteurs

| Acteur | Quoi | Comment il tourne | Coût |
|---|---|---|---|
| **Agent** | Claude Code — lit le repo, code, lance les tests | Agent SDK (accès fichiers + exécution) | Pool crédit Agent SDK (cher) |
| **Superviseur** | Instance Claude — raisonne sur ce que l'agent rapporte | API classique (PAS l'Agent SDK — il ne touche pas le repo) | API standard (moins cher) |
| **Orchestrateur** | Script sans intelligence — route, vérifie le CI, décide quand pinguer | Ton serveur / ta machine | Quasi nul |

Point d'architecture clé : le superviseur n'a PAS besoin des outils de Claude Code. Il raisonne sur
le texte que l'agent produit. Donc il tourne via l'API classique (raisonnement pur), deux fois moins
cher que via l'Agent SDK. Seul l'agent a besoin du SDK.

---

## Le flux de la boucle (V1)

```
1. Orchestrateur → Agent (SDK) : "voici la tâche / le cadrage validé"
2. Agent travaille, produit une sortie (code + éventuellement un push + un job CI)
3. Orchestrateur : VÉRIFIE LE CI LUI-MÊME via l'API GitHub
     - job en queue/in_progress → attend (poll)
     - job rouge → capture les logs
     - job vert → continue
   (NE JAMAIS croire l'agent sur parole quand il dit "c'est vert" — garde-fou anti-faux-vert)
4. Orchestrateur → Superviseur (API) : sortie de l'agent + statut CI réel + contexte de supervision
5. Superviseur répond avec une DÉCISION TYPÉE (voir ci-dessous)
6. Selon le type :
     - CONTINUE → orchestrateur renvoie la consigne à l'agent, retour à l'étape 1
     - PAUSE_HUMAN → orchestrateur PING WhatsApp + gèle la boucle jusqu'à réponse humaine
     - STOP → fin de tâche (brique non-money-path close, ou abandon)
```

---

## La pièce maîtresse : la décision typée du superviseur

Le superviseur reçoit une instruction système qui l'oblige à répondre dans un format structuré
(JSON) que l'orchestrateur peut router sans interpréter. Exemple de schéma :

```json
{
  "decision": "CONTINUE | PAUSE_HUMAN | STOP",
  "reason": "texte court",
  "message_to_agent": "consigne à renvoyer à l'agent (si CONTINUE)",
  "human_ping": "message WhatsApp à l'humain (si PAUSE_HUMAN)",
  "money_path": true/false
}
```

### Règle « quand PAUSE_HUMAN » (le cœur du système)

Le superviseur DOIT renvoyer PAUSE_HUMAN si l'une de ces conditions est vraie :
- **Money-path qui se ferme** : une brique touchant l'argent (soldes, settlement, custody, loyers,
  émission, contrôle de transfert) est prête à être inscrite « franchie ». → OK humain obligatoire.
- **Architecture structurante** : un choix qui change la forme d'un module, une surface réseau, un
  couplage majeur (ex. « couche web sur settlement vs gateway »). → jugement humain.
- **Décision produit** : un choix que seul l'humain a l'information pour trancher (attribution
  initiale, adressage prévente, nature d'un droit). → jugement humain.
- **Drapeau juridique** : tout ce qui touche prévente/collecte/qualification. → jugement humain.
- **Blocage réel** : CI rouge répété (> N fois), agent qui tourne en rond, désaccord non résolu.

Pour TOUT le reste (cadrage de routine, validation d'un test bien fait, correction d'assertion,
inscription d'une brique HABILLAGE), le superviseur renvoie CONTINUE et la boucle avance sans humain.

---

## Les trois garde-fous (non négociables)

1. **Anti-faux-vert** : l'orchestrateur vérifie le statut CI réel via l'API GitHub. Il n'accepte
   jamais « c'est vert » de l'agent sur sa parole. (On a vu plusieurs fois : job en queue annoncé
   vert, ou vert contre H2 au lieu de PostgreSQL.)

2. **Money-path → OK humain** : aucune brique money-path inscrite franchie sans validation humaine
   explicite. Le superviseur prépare et vérifie tout, puis PAUSE_HUMAN avec la preuve. L'humain
   répond oui sur WhatsApp → inscription. Geste de 10 secondes, incompressible.

3. **Anti-dérive** : limite de tours. Si la boucle agent↔superviseur dépasse N allers-retours sur la
   même tâche sans converger → PAUSE_HUMAN même sans blocage formel. (Équivalent automatisé de
   « produit ou rumine ? ».)

---

## Sécurité (à border avant de lancer)

Un agent headless avec accès fichiers + exécution terminal tournant sans surveillance est une
surface d'attaque réelle. Avant de lancer en autonomie :
- **Permissions à portée définie** : limiter les répertoires, commandes et APIs que l'agent peut
  toucher (modèle de permissions scopé de l'Agent SDK). Ne pas lui donner plus que le repo P1.
- **Pas de secret en clair** dans l'environnement de l'orchestrateur (clés API, token GitHub, WhatsApp).
- **Le superviseur ne s'auto-modifie pas** : son instruction système (les règles « quand pinguer »)
  est en lecture seule, versionnée, pas modifiable par la boucle.
- **Limite de dépense** : un plafond de tokens/coût par session, au-delà duquel la boucle s'arrête
  et ping l'humain. Protège du runaway (boucle qui brûle le crédit).

---

## Coût (à connaître AVANT — changement de facturation 15 juin 2026)

- À partir du 15 juin 2026, l'usage programmatique (Agent SDK + claude -p) bascule sur un pool de
  crédit mensuel séparé, facturé au prix API, sans report. Chat interactif et terminal interactif
  NON affectés.
- Ordre de grandeur du crédit inclus : ~20 $ (Pro), ~100 $ (Max 5x), ~200 $ (Max 20x) / mois.
- Une session lourde brûle 0,5–1M tokens. La boucle fait tourner DEUX instances (agent + superviseur)
  → consommation ~doublée vs un agent seul. D'où l'intérêt de mettre le superviseur sur l'API
  classique (moins cher) et de mesurer la consommation réelle en V1 avant d'étendre.
- À faire cette semaine : réclamer le crédit unique annoncé par Anthropic (action manuelle dans les
  paramètres de compte), et mesurer la consommation actuelle pour budgéter.

---

## Périmètre V1 (minimal, pour prouver et mesurer)

INCLUS :
- Boucle agent↔superviseur sur les tâches NON money-path (cadrage, habillage, corrections de tests).
- Vérification CI automatique via API GitHub (garde-fou anti-faux-vert).
- Décision typée du superviseur (CONTINUE / PAUSE_HUMAN / STOP).
- Ping WhatsApp sur PAUSE_HUMAN.
- Limite de tours + plafond de dépense.

EXCLUS de V1 (ajoutés seulement si V1 est concluant) :
- L'automatisation des tâches money-path (restent supervisées manuellement par toi en V1).
- Le « Remote Control » / multi-agents parallèles.
- Toute logique fine au-delà des règles PAUSE_HUMAN ci-dessus.

Critère de succès V1 : la boucle close seule au moins une brique habillage de bout en bout, te
pingue correctement sur une décision money-path, et tu as une mesure réelle du coût en tokens.

---

## Ce que la V1 ne change PAS

- La méthode de supervision reste identique (prouver pas prétendre, money-path = rigueur max,
  inventaire des chemins, etc.) — elle est juste portée dans l'instruction système du superviseur.
- Le repo reste la source de vérité unique.
- Toi tu restes le décideur sur tout ce qui touche l'argent et la stratégie.
- Le SUPERVISION-CONTEXT.md reste le fichier qui amorce le superviseur (humain ou automatisé).
