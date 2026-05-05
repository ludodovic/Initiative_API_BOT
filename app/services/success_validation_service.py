from typing import Any

from app.db import get_database

CONFIG_COLLECTION = "bot_config"
SUCCESS_COLLECTION = "succes"
VALIDATION_COLLECTION = "success_validations"
USER_COLLECTION = "users"

SUCCES_LIST = ["Harcèlement moral",
"Et ça fait bim bam boum",
"Décalage horaire",
"La hateuse originelle",
"Zone d'inconfort",
"L'inventeur",
"Petit ange parti trop tôt",
"Ils sont trop nombreux",
"Droit dans le mur",
"Pokédex complet",
"Il court vite le coquin",
"C'est qui çui-là ?",
"Petite joueuse",
"Il est timide",
"Il a peut-être trop mangé ?",
"Il fait un peu frais là non ?",
"Quitte ou double",
"Plus là le bambou",
"Accro aux réseaux sociaux",
# "100% de présence",
"Célébrité",
"Aligné",
"First !",
"Je sais ce que je veux",
"Amasseur de guildatons",
"Missionné",
"Onzième position du Kamasutra",
"Il y a toujours un plus gros poisson",
"Speedrunner",
"Une fine équipe",
"Chamailleries",
"Compétition amicale",
"Tu l'as bien mérité",
"Long live the King",
"Humiliation",
"Mutinerie",
"Pardon j'ai cru que c'était un bot",
"L'important c'est de participer",
"C'est la fête",
"Jure c'est pas des bots ?",
"De très bons amis",
"Généreux",
"Ça existe ce truc ?",
"Un engrais de qualité",
"Le grand remplacement",
"Membre exemplaire",
"Heures supp'",
"Membre actif",
"Recruteur",
"Ça enchaîne !",
"PGM",
"Complètement dérangés",
"Les naturistes",
"Justiciers gantés",
"Tema la taille du rat",
"Talon d'Achille",
"Je sais pas qui c'est mais je prends les points",
"Point faible : trop fort",
"Apprenti soloteur",
"La meilleure défense, c'est l'attaque !",
"La prochaine sera meilleure",
"Sacré duo",
"TGIF",
"Une simple formalité",
"Les petits aussi",
"Expédition Club Med",
"Songe d'une nuit d'été",
"Unique en son genre",
"L'anomalie, c'est nous",
"Et tout le tralala",
"La chatte qu'il a !!!",
"Drop \"rare\"",
"Plus que des camarades de guilde",
"J'apporte les œufs et toi le sucre",
"Il joue quelle classe celui là déjà ?",
"Flashmob",
"Une bonne petite communauté",
"Grande famille"]


async def set_validation_channel(guild_id: int, channel_id: int) -> None:
    database = await get_database()
    await database[CONFIG_COLLECTION].update_one(
        {"guild_id": guild_id},
        {"$set": {"validation_channel_id": channel_id}},
        upsert=True,
    )


async def get_validation_channel(guild_id: int) -> int | None:
    database = await get_database()
    config = await database[CONFIG_COLLECTION].find_one({"guild_id": guild_id})
    if config is None:
        return None

    channel_id = config.get("validation_channel_id")
    return int(channel_id) if channel_id else None


async def find_success(success_reference: str) -> dict[str, Any] | None:
    database = await get_database()

    if success_reference.isdigit():
        success_id = int(success_reference)
        category = await database[SUCCESS_COLLECTION].find_one({"catList.id": success_id})
        return _find_success_in_category_by_id(category, success_id) if category else None

    success_name = _find_success_name_from_list(success_reference)
    if success_name is None:
        return None

    category = await database[SUCCESS_COLLECTION].find_one({"catList.name": success_name})
    return _find_success_in_category_by_name(category, success_name) if category else None


def _find_success_name_from_list(success_reference: str) -> str | None:
    normalized_reference = _normalize_success_name(success_reference)
    normalized_names = {
        _normalize_success_name(success_name): success_name
        for success_name in SUCCES_LIST
    }

    if normalized_reference in normalized_names:
        return normalized_names[normalized_reference]

    for normalized_name, success_name in normalized_names.items():
        if normalized_name.startswith(normalized_reference):
            return success_name

    for normalized_name, success_name in normalized_names.items():
        if normalized_reference in normalized_name:
            return success_name

    reference_tokens = set(normalized_reference.split())
    if not reference_tokens:
        return None

    best_name: str | None = None
    best_score = 0.0
    for normalized_name, success_name in normalized_names.items():
        name_tokens = set(normalized_name.split())
        common_tokens = reference_tokens & name_tokens
        if not common_tokens:
            continue

        score = len(common_tokens) / len(reference_tokens | name_tokens)
        if score > best_score:
            best_score = score
            best_name = success_name

    return best_name if best_score >= 0.5 else None


async def create_validation_request(
    guild_id: int,
    channel_id: int,
    message_id: int,
    requester_discord_username: str,
    member_discord_username: str,
    member_display_name: str,
    success_id: int,
    success_name: str,
) -> None:
    database = await get_database()
    await database[VALIDATION_COLLECTION].insert_one(
        {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "requester_discord_username": requester_discord_username,
            "member_discord_username": member_discord_username,
            "member_display_name": member_display_name,
            "success_id": success_id,
            "success_name": success_name,
            "status": "pending",
        }
    )


async def get_validation_request(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    return _serialize(validation) if validation else None


async def approve_validation(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    if validation is None or validation.get("status") != "pending":
        return _serialize(validation) if validation else None

    await database[USER_COLLECTION].update_one(
        {"discord_username": validation["member_discord_username"]},
        {"$addToSet": {"achievement": validation["success_id"]}},
    )
    await database[VALIDATION_COLLECTION].update_one(
        {"message_id": message_id},
        {"$set": {"status": "approved"}},
    )
    validation["status"] = "approved"
    return _serialize(validation)


async def refuse_validation(message_id: int) -> dict[str, Any] | None:
    database = await get_database()
    validation = await database[VALIDATION_COLLECTION].find_one_and_update(
        {"message_id": message_id, "status": "pending"},
        {"$set": {"status": "refused"}},
    )
    if validation is None:
        validation = await database[VALIDATION_COLLECTION].find_one({"message_id": message_id})
    if validation:
        validation["status"] = "refused"
    return _serialize(validation) if validation else None


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "_id"}


def _find_success_in_category_by_id(
    category: dict[str, Any],
    success_id: int,
) -> dict[str, Any] | None:
    for success in category.get("catList", []):
        if success.get("id") == success_id:
            return _serialize_success(success)
    return None


def _find_success_in_category_by_name(
    category: dict[str, Any],
    success_name: str,
) -> dict[str, Any] | None:
    for success in category.get("catList", []):
        if success.get("name") == success_name:
            return _serialize_success(success)
    return None


def _serialize_success(success: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": success["id"],
        "name": success["name"],
        "value": success.get("value", 0),
        "icon": success.get("icon", ""),
        "desc": success.get("desc", ""),
    }


def _normalize_success_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())
