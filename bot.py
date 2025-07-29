import discord
from discord.ext import commands
import json
import asyncio
import time
import unicodedata
import os
import logging

# ----- CONFIGURATION -----
TOKEN = os.getenv('TOKEN')
QUIZZ_CHANNEL_ID = 1392554666591785040 #1392554666591785040
EMETTEUR_CHANNEL_ID = 1394694775063711844 #1394694775063711844
ORGANISATEUR_ROLE = 'Game master'
COOLDOWN = 29 * 60  # 30 min en secondes

# ----- INITIALISATION -----
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ----- DONNEES -----
current_answer = None
current_data = {}
is_game_active = False
last_attempts = {}  # user_id: timestamp
guessed_names = set()  # noms déjà proposés

# ----- UTILITAIRES -----
def remove_accents(text):
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

def normalize_name(name):
    return remove_accents(name.strip().lower())

def has_role(member, role_name):
    return any(role.name == role_name for role in member.roles)

# ----- CHARGEMENT DES PERSONNAGES -----
def load_characters():
    with open('characters.json', 'r', encoding='utf-8') as f:
        raw = json.load(f)
        return {normalize_name(char['nom']): char for char in raw}

characters = load_characters()

# ----- COMMANDES -----
@bot.command()
@commands.has_role(ORGANISATEUR_ROLE)
async def dle_start(ctx, *, character_name):
    global is_game_active, current_answer, current_data, guessed_names

    if ctx.channel.id != EMETTEUR_CHANNEL_ID:
        await ctx.send("❌ Cette commande doit être utilisée dans le salon émetteur.")
        return

    key = normalize_name(character_name)

    """if key not in characters:
        await ctx.send("❌ Ce personnage n'est pas dans la base de données.")
        return"""

    current_answer = key
    current_data = characters[key]
    is_game_active = True
    guessed_names = set()

    quizz_channel = bot.get_channel(QUIZZ_CHANNEL_ID)
    if quizz_channel:
        await quizz_channel.send("🎮 Nouvelle partie DLE lancée ! Utilisez `!devine NomDuPersonnage` pour participer. Une tentative toutes les 30 minutes par joueur.")
    await ctx.send("✅ Personnage sélectionné, partie démarrée.")

@bot.command()
@commands.has_role(ORGANISATEUR_ROLE)
async def dle_stop(ctx):
    global is_game_active, current_answer, current_data, guessed_names
    is_game_active = False
    current_answer = None
    current_data = {}
    guessed_names = set()

    # Message dans le salon émetteur (où la commande a été envoyée)
    await ctx.send("🛑 Partie DLE terminée par l'organisateur.")

    # Envoi d'un message dans le salon quizz
    quizz_channel = bot.get_channel(QUIZZ_CHANNEL_ID)
    if quizz_channel:
        await quizz_channel.send("🛑 La partie DLE a été arrêtée par l'organisateur.")


@bot.command()
async def dle_status(ctx):
    if is_game_active:
        await ctx.send("✅ Une partie est en cours ! Envoyez `!devine NomDuPersonnage` pour jouer.")
    else:
        await ctx.send("❌ Aucune partie active en ce moment.")

@bot.command()
async def devine(ctx, *, guess):
    global is_game_active, current_answer, current_data, last_attempts, guessed_names

    if not is_game_active:
        await ctx.send("❌ Aucun jeu en cours.")
        return

    if ctx.channel.id != QUIZZ_CHANNEL_ID:
        return

    guess_key = normalize_name(guess)
    user_id = ctx.author.id
    now = time.time()

    if guess_key in guessed_names:
        await ctx.send(f"⚠️ {ctx.author.mention}, ce personnage a déjà été proposé. Tente autre chose !")
        return

    if guess_key not in characters:
        await ctx.send(f"❌ {ctx.author.mention}, ce personnage n'existe pas dans la base. Pas d'inquiétude, vous pouvez retenter sans attendre.")
        return

    # Appliquer le cooldown seulement si la proposition est valide
    if not has_role(ctx.author, ORGANISATEUR_ROLE):
        if user_id in last_attempts and now - last_attempts[user_id] < COOLDOWN:
            remaining = int(COOLDOWN - (now - last_attempts[user_id])) // 60
            await ctx.send(f"⏳ {ctx.author.mention}, vous devez attendre encore {remaining} minutes avant de rejouer.")
            return
        last_attempts[user_id] = now

    guessed_names.add(guess_key)
    guessed_data = characters[guess_key]

    feedback = []
    for key in current_data:
        target = current_data[key]
        player = guessed_data.get(key, "unknown")

        # Comparaison pour les attributs numériques ou "unknown"
        if key in ["total de pouvoir", "age", "taille"]:
            if isinstance(target, int) and isinstance(player, int):
                if player == target:
                    result = "✅"
                elif player > target:
                    result = "🔽"
                else:
                    result = "🔼"
                feedback.append(f"**{key.capitalize()}** : {player} {result}")
            elif isinstance(target, int) and isinstance(player, str) and player.lower() == "unknown":
                feedback.append(f"**{key.capitalize()}** : unknown ❌")
            elif isinstance(player, int) and isinstance(target, str) and target.lower() == "unknown":
                feedback.append(f"**{key.capitalize()}** : {player} ❌")
            else:
                result = "✅" if str(player).lower() == str(target).lower() else "❌"
                feedback.append(f"**{key.capitalize()}** : {player} {result}")

        # Comparaison pour les listes (type de magie)
        elif key == "type de magie":
            if isinstance(target, list) and isinstance(player, list):
                communs = [t for t in player if t in target]
                tous = list(set(player + target))
                if communs:
                    # Si le joueur a deviné un ou plusieurs bons éléments
                    symbols = " ✅"
                    if len(set(target)) > len(communs):
                        symbols += " ,❌"
                    feedback.append(f"**{key.capitalize()}** : {', '.join(commun for commun in communs)}{symbols}")
                else:
                    feedback.append(f"**{key.capitalize()}** : {', '.join(player)} ❌")
            else:
                result = "✅" if player == target else "❌"
                feedback.append(f"**{key.capitalize()}** : {player} {result}")

        # Comparaison normale (nom, race, sexe, groupe, arme)
        else:
            result = "✅" if str(player).lower() == str(target).lower() else "❌"
            feedback.append(f"**{key.capitalize()}** : {player} {result}")

    response = f"🔎 Tentative de {ctx.author.mention} : **{guessed_data['nom']}**\n" + "\n".join(feedback)
    await ctx.send(response)

    if guess_key == current_answer:
        await ctx.send(f"🎉 Bravo {ctx.author.mention} ! La bonne réponse était **{current_data['nom']}**. Partie terminée.")
        emetteur_channel = bot.get_channel(EMETTEUR_CHANNEL_ID)
        if emetteur_channel:
            await emetteur_channel.send(f"{ctx.author.display_name} a trouvé la bonne réponse. Fin de la partie.")
        is_game_active = False
        current_answer = None
        current_data = {}
        last_attempts = {}
        guessed_names = set()

@bot.event #si le bot se deconnecte
async def on_disconnect():
    quizz_channel = bot.get_channel(QUIZZ_CHANNEL_ID)
    emetteur_channel = bot.get_channel(EMETTEUR_CHANNEL_ID)

    message = "⚠️ Le bot vient de se déconnecter. Si une partie était en cours, elle est suspendue."

    if quizz_channel:
        await quizz_channel.send(message)
    if emetteur_channel and emetteur_channel != quizz_channel:
        await emetteur_channel.send(message)



# ----- DEMARRAGE -----
logger = logging.getLogger(__name__)
logging.basicConfig(encoding='utf-8', level=logging.DEBUG)
logger.warning("Bot prêt à démarrer...")
logger.info("Personnages chargés :", list(characters.keys()))
bot.run(TOKEN)
