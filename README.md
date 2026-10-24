# Biozy — bot Discord de stylisation de texte

Biozy surveille un salon choisi par un administrateur. Lorsqu'un membre y
envoie du texte, le bot tente de supprimer le message original, génère jusqu'à
cinq variantes décorées. Un embed public compact affiche l'étape de traitement
actuelle sans s'allonger au fil de la progression. À la fin, un bouton permet
à l'auteur de recevoir chaque suggestion dans un bloc de code par réponse
éphémère, invisible aux autres membres. Le suivi est supprimé dès que l'auteur
affiche ses suggestions, ou après 1 minute s'il ne clique pas. Les réponses
éphémères sont supprimées après 1 minute.

## Architecture

- `main.py` : intents, commandes préfixées, extensions et session HTTP partagée.
- `cogs/general.py` : commandes `.help` et `.ping`.
- `cogs/config.py` : `.configbio`, affichage de configuration et contrôle
  d'accès administrateur.
- `cogs/admin.py` : commande `.viderbio`, confirmation et suppression de
  l'historique du salon configuré.
- `cogs/bio.py` : traitement des messages, suivi détaillé, limitation de
  fréquence et remise privée des suggestions par interaction.
- `services/fancytext.py` : client TheFancyText.
- `services/generatefancytext.py` : client GenerateFancyText.
- `services/styler.py` : composition locale, décoration et déduplication.
- `services/config_store.py` : sauvegarde JSON par serveur, chargée en mémoire
  pour éviter une lecture disque à chaque message.
- `data/config.json` : association des serveurs aux salons surveillés.

## APIs vérifiées

### TheFancyText

Documentation et conditions officielles :

- <https://www.thefancytext.com/developer-documentation>
- <https://www.thefancytext.com/terms-and-conditions>

Le service documente `POST https://www.thefancytext.com/api/font` avec un
corps JSON `{"text": "...", "size": 1000}`. La réponse contient
`results: [{"name": "...", "text": "..."}]`; les entrées dont le nom commence
par `rup5050rup_` sont des titres de section, écartés par Biozy. Le texte est
limité à 500 caractères par la documentation. Aucune clé n'est demandée.
L'API ne publie pas de limite de débit : ses conditions demandent de mettre en
cache les résultats, de faire des requêtes raisonnables et de contacter le
service avant un usage important. Le client Biozy met les résultats en cache
pendant 15 minutes au maximum et espace ses appels. Les conditions interdisent
notamment de perturber le service ou de republier ses outils comme les siens.

### GenerateFancyText

Documentation et conditions officielles :

- <https://www.generatefancytext.com/api-docs/>
- <https://www.generatefancytext.com/terms/>

La documentation indique un `GET` vers
`https://www.generatefancytext.com/api/generate.json` avec le paramètre
`text`. Les paramètres facultatifs documentés sont `decor` et `modifiers`.
Biozy utilise un seul appel sans décoration optionnelle : la réponse fournit
les styles, puis les décorations sont composées localement. Le format vérifié
est `{"success": true, "original": "...", "count": ..., "results":
[{"id": "...", "name": "...", "result": "..."}]}`. La documentation indique
que l'API est actuellement gratuite et demande de rester sous 50 requêtes par
minute. Biozy espace ses appels à au moins 1,3 seconde et met les résultats
en cache pendant 15 minutes au maximum. Les conditions imposent un usage légal
et interdisent notamment de perturber le service ou d'usurper une identité.

Les deux services sont fournis sans garantie de disponibilité. Si l'un échoue,
Biozy continue avec l'autre et les décorations locales. Si les deux échouent,
les décorations locales peuvent encore fournir des résultats.

## Visibilité et limites Discord

- Le texte original est conservé en mémoire pour créer les suggestions et
  peut être présent dans les caches API pendant 15 minutes au maximum. Les
  caches sont bornés, non persistants, et le code ne journalise pas le texte.
- Biozy essaie de supprimer le message original dès réception. Il faut lui
  accorder **Gérer les messages** dans le salon. Sans cette permission, Biozy
  le signale discrètement, mais ne prétend pas l'avoir supprimé.
- L'embed public de suivi ne contient jamais le texte soumis ni les
  suggestions et ne montre que l'étape actuelle. Le bouton final ne révèle les
  suggestions que dans des réponses éphémères à l'auteur ; les autres membres
  ne peuvent pas les consulter.
- Les suggestions éphémères sont envoyées une par message en bloc de code,
  afin de faciliter leur copie. Les espaces et retours à la ligne sont
  normalisés pour éviter qu'une variante se présente différemment.
- Le bot supprime le message original s'il en a la permission, puis supprime
  immédiatement son embed de suivi quand l'auteur demande ses suggestions
  privées (ou après 1 minute sans clic). Les réponses éphémères disparaissent
  après 1 minute et les avertissements temporaires après 10 secondes. Le
  traitement normal n'efface pas les autres messages des membres.
- Un administrateur peut lancer `.viderbio` pour effacer l'historique
  supprimable du salon configuré. Biozy demande une confirmation valable
  30 secondes et vérifie ses permissions avant le nettoyage. Cette action
  inclut les messages des membres dans ce salon et ne peut pas être annulée;
  elle n'efface pas les autres salons.
- Le texte est limité à 500 caractères. Les demandes d'un même membre sont
  espacées d'au moins 15 secondes par serveur; une activité sur un serveur
  n'empêche donc pas ce membre d'utiliser Biozy dans un autre serveur.
- Les appels vers les deux fournisseurs de styles sont lancés en parallèle
  pour chaque demande. Chaque fournisseur conserve son propre cache global et
  son limiteur de débit partagé entre les serveurs : cela évite les requêtes
  répétées et protège les APIs quand l'activité augmente.
- Les configurations restent séparées par identifiant de serveur. Les requêtes
  HTTP sont partagées et réutilisées; les traitements et leurs embeds restent
  associés à leur salon d'origine.
- Les erreurs d'une demande ou d'une interaction sont journalisées sans le
  texte soumis et ne mettent pas fin au bot. Les erreurs d'API utilisent
  l'autre fournisseur ou le secours local; les messages d'erreur affichés par
  Biozy sont en anglais. Une configuration ou un token invalide au démarrage
  reste une erreur fatale explicite, car le bot ne peut pas fonctionner de
  façon fiable sans eux.
- L'embed de progression affiche uniquement l'étape actuelle sans le texte
  soumis. Une fois terminé, son bouton donne accès aux suggestions privées et
  le suivi est supprimé dès la première suggestion envoyée.
- Biozy utilise uniquement des commandes préfixées par `.`. Il ne crée pas de
  commandes slash.

## Installation et lancement sur Windows

1. Installe Python 3.12 ou plus récent.
2. Ouvre PowerShell dans le dossier `D:\Biozy`.
3. Crée puis active un environnement virtuel :

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Installe les dépendances :

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Dans `.env`, renseigne `DISCORD_TOKEN` avec le token du bot. Ne partage
   jamais ce fichier et ne publie pas le token.
6. Dans le Discord Developer Portal, ouvre l'application, puis **Bot**, et
   active **Message Content Intent**. Ce réglage est obligatoire en plus de
   l'intent activé dans `main.py`.
7. Invite le bot sur ton serveur avec les permissions minimales suivantes :
   **View Channel**, **Read Message History**, **Send Messages**, **Embed Links**
   et **Manage Messages** dans le salon configuré. **Read Message History**
   est nécessaire à `.viderbio`. Aucun droit Administrateur n'est nécessaire
   pour le bot.
8. Lance le bot :

   ```powershell
   python main.py
   ```

9. Dans le serveur, un administrateur utilise `.configbio #salon`. `.configbio`
   affiche le salon actuel et `.configbio off` désactive le traitement.
   `.viderbio` nettoie l'historique du salon Biozy après confirmation.
10. Publie un message de test dans le salon configuré. Biozy affiche un embed
    compact indiquant l'étape en cours, supprime le message original si
    possible, puis affiche un bouton de résultat. L'auteur clique dessus pour
    recevoir des suggestions copiables en réponses éphémères; l'embed disparaît
    immédiatement au clic ou après 1 minute sans clic.

## Tests

Lance les tests unitaires :

```powershell
python -m unittest discover -s tests -v
```

Checklist de validation Discord :

- [ ] `.help` et `.ping` répondent; aucune commande slash n'est créée.
- [ ] `.configbio` affiche l'état; `.configbio #salon` configure un salon;
  `.configbio off` le désactive.
- [ ] `.viderbio` est réservé aux administrateurs, demande confirmation,
  puis supprime les messages supprimables du salon configuré seulement.
- [ ] Un membre sans permission Administrateur ne peut pas configurer Biozy.
- [ ] Le bot fonctionne avec seulement les permissions listées plus haut;
  **Read Message History** permet à `.viderbio` de parcourir l'historique.
- [ ] Les commandes, bots, messages vides et messages hors du salon sont ignorés.
- [ ] Un message admissible est supprimé si **Gérer les messages** est accordé.
- [ ] Sans permission de suppression, le bot avertit le membre sans révéler le texte.
- [ ] L'embed décrit les étapes en cours sans révéler le texte soumis.
- [ ] Le bouton de résultat montre les suggestions en blocs copiables
  uniquement à l'auteur via des réponses éphémères; aucun DM n'est envoyé.
- [ ] Le suivi disparaît au clic sur le bouton ou après 1 minute sans clic;
  les résultats éphémères disparaissent après 1 minute et les avertissements
  temporaires après 10 secondes.
- [ ] En dehors de `.viderbio`, le bot ne supprime aucun autre message membre.
- [ ] Les erreurs HTTP, JSON invalide, API indisponible et réponse vide
  n'arrêtent pas le bot et déclenchent le secours de l'autre API/local.
- [ ] Les mentions générées ne notifient personne; le texte et le token
  n'apparaissent pas dans les logs.

## Déploiement Linux avec systemd

Exemple si le projet se trouve dans `/opt/biozy`. Choisis une machine Linux
compatible Python 3.12 ou plus récent; la disponibilité 24 h/24 dépend de
l'hébergeur et n'est pas garantie par le code.

1. Copie le projet dans `/opt/biozy`, puis crée l'environnement et installe
   les dépendances :

   ```bash
   cd /opt/biozy
   python3.12 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Renseigne le token dans `/opt/biozy/.env`, puis protège le fichier :

   ```bash
   chmod 600 /opt/biozy/.env
   ```

3. Crée un compte système `biozy` non privilégié. Il doit pouvoir lire le
   projet et écrire dans `/opt/biozy/data/config.json`.
4. Crée `/etc/systemd/system/biozy.service` :

   ```ini
   [Unit]
   Description=Biozy Discord bot
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=biozy
   WorkingDirectory=/opt/biozy
   ExecStart=/opt/biozy/.venv/bin/python /opt/biozy/main.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

5. Recharge systemd et active le service au démarrage :

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now biozy
   ```

6. Vérifie l'état, consulte les logs ou redémarre après une mise à jour :

   ```bash
   sudo systemctl status biozy
   sudo journalctl -u biozy -f
   sudo systemctl restart biozy
   ```

## Déploiement sur Botkeep

Le guide Botkeep documente l'import d'un projet Python depuis GitHub. Dans le
tableau de bord Botkeep, connecte GitHub et autorise l'accès au dépôt
`bluesplanet/Biozy`, puis sélectionne la branche `main` et la racine du projet
(le dossier qui contient `requirements.txt`). Vérifie le runtime Python et
utilise cette commande de démarrage :

```text
python main.py
```

Ajoute `DISCORD_TOKEN` dans la section des secrets ou variables protégées de
Botkeep. Ne téléverse pas `.env` et ne mets jamais le token dans GitHub. Active
également **Message Content Intent** dans le portail développeur Discord et
accorde au bot les permissions minimales listées dans la section Windows.

Biozy sauvegarde les configurations de serveur dans `data/config.json`. Vérifie
que le stockage de l'application conserve les fichiers écrits entre les
redémarrages; le code du bot ne peut pas garantir la persistance propre à
l'hébergeur. Après le démarrage, configure le salon avec `.configbio #salon`
et vérifie les journaux de l'application dans le tableau de bord Botkeep.
