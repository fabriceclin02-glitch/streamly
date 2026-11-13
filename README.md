# STREAMLY

Plateforme de streaming 100 % légale : films du domaine public et sous licence libre (lecture intégrale),
chaînes TV gratuites, et rangée **« L'IA au cinéma »** (fiches, jaquettes, bandes-annonces officielles et
plateformes légales pour les films protégés comme *Judge Dredd*, *Paycheck* ou *I, Robot*).

Site : https://fabriceclin02-glitch.github.io/streamly/

## Catalogue automatique
`scripts/update_catalog.py` (Python 3, sans dépendance) récupère chaque jour :
- les films libres d'Internet Archive et de Wikimedia Commons (lisibles sur STREAMLY) ;
- les films d'IA / robots (Wikidata + TMDB) avec jaquette, bande-annonce et offres légales en France.

Les jaquettes ne sont **pas hébergées** : le site charge directement les images depuis archive.org,
image.tmdb.org et Wikimedia.

La mise à jour tourne seule chaque jour (`.github/workflows/update-catalog.yml`).
Pour lancer à la main : onglet **Actions › Mise à jour du catalogue › Run workflow**.
En local : `python scripts/update_catalog.py`

### Jaquettes et bandes-annonces (recommandé)
1. Créez un compte gratuit sur https://www.themoviedb.org puis une clé API (Paramètres › API).
2. Sur GitHub : **Settings › Secrets and variables › Actions › New repository secret**,
   nom `TMDB_API_KEY`, valeur = la clé (ou le « jeton d'accès en lecture »).
3. Lancez le workflow. Ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB.
