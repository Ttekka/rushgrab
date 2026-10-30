# rushgrab

Petite app Windows pour récupérer une vidéo YouTube en MP4 ou MP3, prête pour le montage. L'interface s'inspire de [cobalt](https://cobalt.tools).

## Utilisation

1. Télécharge `rushgrab.exe` dans les [Releases](../../releases/latest).
2. Lance-le. Au premier démarrage, l'app installe ses outils (environ 160 Mo, quelques secondes).
3. Colle le lien, choisis MP4 ou MP3, puis clique sur « télécharger ».

Windows peut afficher « Windows a protégé votre ordinateur », car l'exe n'est pas signé : clique sur « Informations complémentaires », puis « Exécuter quand même ».

## Formats

| Choix | Fichier obtenu |
| --- | --- |
| MP4 jusqu'à 1080p | H.264 + AAC, sans réencodage quand YouTube le propose |
| MP4 1440p et 2160p | YouTube ne fournit que du VP9 ou de l'AV1 à ces tailles : l'app convertit en H.264, ce qui prend plus de temps |
| MP3 | 320 kbps à débit constant, pour éviter les décalages de son dans Premiere |

Une vidéo moins haute que la qualité choisie est récupérée dans sa meilleure qualité disponible. Un lien de playlist ne télécharge que la vidéo ouverte.

## Fonctionnement

L'app ne passe pas par cobalt : son instance publique est réservée à son propre site et ne prend plus YouTube en charge. Elle pilote en local [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org) et [Deno](https://deno.com), installés dans `%LOCALAPPDATA%\rushgrab\bin`. yt-dlp se met à jour à chaque démarrage, pour suivre les changements de YouTube.

En cas d'échec, le détail se trouve dans `%LOCALAPPDATA%\rushgrab\dernier-telechargement.log`.

Télécharge uniquement des vidéos que tu as le droit d'utiliser.

## Développement

Il faut Python 3.11 ou plus récent. Pour construire `dist\rushgrab.exe` :

```powershell
.\build.ps1
```
