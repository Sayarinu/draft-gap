from services.bookie import (
    _build_market_catalog_from_page_text,
    _extract_from_page_text,
    find_market_set_for_match,
    resolve_match_odds,
)


THUNDERPICK_CARD_TEXT = """
SK Gaming 2.50 vs 1.48 Team Heretics
Movistar KOI 1.28 vs 3.30 Fnatic
Ninjas in Pyjamas 1.49 vs 2.55 OMG
Team WE 1.45 vs 2.66 ThunderTalk Gaming
paiN Gaming 2.40 vs 1.50 Keyd Stars
Fluxo W7M 1.50 vs 2.40 Leviatán
"""


def test_build_market_catalog_parses_moneyline_handicap_and_total_maps() -> None:
    text = """
    Alpha 1.80 vs Beta 2.05
    Map Handicap
    Alpha -1.5 2.90
    Beta +1.5 1.35
    Total Maps
    Over 2.5 2.10
    Under 2.5 1.70
    """

    catalog = _build_market_catalog_from_page_text(text)

    assert len(catalog["matches"]) == 1
    offers = catalog["matches"][0]["offers"]
    assert any(offer["market_type"] == "match_winner" and offer["selection_key"] == "team1" for offer in offers)
    assert any(offer["market_type"] == "map_handicap" and offer["selection_key"] == "team1_-1.5" for offer in offers)
    assert any(offer["market_type"] == "total_maps" and offer["selection_key"] == "over_2.5" for offer in offers)


def test_find_market_set_remaps_selections_to_team_a_and_team_b() -> None:
    catalog = {
        "version": 2,
        "source_book": "thunderpick",
        "scraped_at": "2026-03-28T00:00:00Z",
        "matches": [
            {
                "team1": "Alpha",
                "team2": "Beta",
                "offers": [
                    {
                        "source_book": "thunderpick",
                        "market_type": "match_winner",
                        "selection_key": "team1",
                        "line_value": None,
                        "decimal_odds": 1.8,
                        "market_status": "available",
                        "scraped_at": None,
                        "source_market_name": "Match Winner",
                        "source_selection_name": "Alpha",
                        "source_payload_json": None,
                    },
                    {
                        "source_book": "thunderpick",
                        "market_type": "map_handicap",
                        "selection_key": "team2_+1.5",
                        "line_value": 1.5,
                        "decimal_odds": 1.4,
                        "market_status": "available",
                        "scraped_at": None,
                        "source_market_name": "Map Handicap",
                        "source_selection_name": "Beta",
                        "source_payload_json": None,
                    },
                ],
            }
        ],
    }

    market_set = find_market_set_for_match("Alpha", "Beta", catalog)

    assert market_set["matched"] is True
    assert any(offer["selection_key"] == "team_a" for offer in market_set["offers"])
    assert any(offer["selection_key"] == "team_b_+1.5" for offer in market_set["offers"])


def test_find_market_set_matches_team_we_and_thundertalk_aliases_in_reverse_order() -> None:
    catalog = {
        "version": 2,
        "source_book": "thunderpick",
        "scraped_at": "2026-03-28T00:00:00Z",
        "matches": [
            {
                "team1": "ThunderTalk Gaming",
                "team2": "Team WE",
                "offers": [
                    {
                        "source_book": "thunderpick",
                        "market_type": "match_winner",
                        "selection_key": "team1",
                        "line_value": None,
                        "decimal_odds": 1.91,
                        "market_status": "available",
                        "scraped_at": None,
                        "source_market_name": "Match Winner",
                        "source_selection_name": "ThunderTalk Gaming",
                        "source_payload_json": None,
                    },
                    {
                        "source_book": "thunderpick",
                        "market_type": "match_winner",
                        "selection_key": "team2",
                        "line_value": None,
                        "decimal_odds": 1.95,
                        "market_status": "available",
                        "scraped_at": None,
                        "source_market_name": "Match Winner",
                        "source_selection_name": "Team WE",
                        "source_payload_json": None,
                    },
                ],
            }
        ],
    }

    market_set = find_market_set_for_match("WE", "ThunderTalk", catalog)

    assert market_set["matched"] is True
    assert market_set["confidence"] == "exact"
    assert market_set["matched_row_team1"] == "Team WE"
    assert market_set["matched_row_team2"] == "ThunderTalk Gaming"
    assert any(
        offer["selection_key"] == "team_a" and offer["source_selection_name"] == "WE"
        for offer in market_set["offers"]
    )
    assert any(
        offer["selection_key"] == "team_b" and offer["source_selection_name"] == "ThunderTalk"
        for offer in market_set["offers"]
    )


def test_extract_from_page_text_supports_real_thunderpick_card_layout() -> None:
    rows = _extract_from_page_text(THUNDERPICK_CARD_TEXT)

    assert rows == [
        {"team1": "SK Gaming", "team2": "Team Heretics", "odds1": 2.5, "odds2": 1.48},
        {"team1": "Movistar KOI", "team2": "Fnatic", "odds1": 1.28, "odds2": 3.3},
        {"team1": "Ninjas in Pyjamas", "team2": "OMG", "odds1": 1.49, "odds2": 2.55},
        {"team1": "Team WE", "team2": "ThunderTalk Gaming", "odds1": 1.45, "odds2": 2.66},
        {"team1": "paiN Gaming", "team2": "Keyd Stars", "odds1": 2.4, "odds2": 1.5},
        {"team1": "Fluxo W7M", "team2": "Leviatán", "odds1": 1.5, "odds2": 2.4},
    ]


def test_extract_from_page_text_preserves_existing_supported_layouts() -> None:
    assert _extract_from_page_text("Team WE 1.45 vs ThunderTalk Gaming 2.66") == [
        {
            "team1": "Team WE",
            "team2": "ThunderTalk Gaming",
            "odds1": 1.45,
            "odds2": 2.66,
        }
    ]
    assert _extract_from_page_text("1.45 Team WE vs 2.66 ThunderTalk Gaming") == [
        {
            "team1": "Team WE",
            "team2": "ThunderTalk Gaming",
            "odds1": 1.45,
            "odds2": 2.66,
        }
    ]


def test_build_market_catalog_preserves_real_thunderpick_card_team_names() -> None:
    catalog = _build_market_catalog_from_page_text(THUNDERPICK_CARD_TEXT)

    assert [
        (match["team1"], match["team2"])
        for match in catalog["matches"]
    ] == [
        ("SK Gaming", "Team Heretics"),
        ("Movistar KOI", "Fnatic"),
        ("Ninjas in Pyjamas", "OMG"),
        ("Team WE", "ThunderTalk Gaming"),
        ("paiN Gaming", "Keyd Stars"),
        ("Fluxo W7M", "Leviatán"),
    ]


def test_find_market_set_matches_team_we_and_thundertalk_from_real_card_catalog() -> None:
    catalog = _build_market_catalog_from_page_text(THUNDERPICK_CARD_TEXT)

    market_set = find_market_set_for_match("Team WE", "ThunderTalk Gaming", catalog)

    assert market_set["matched"] is True
    assert market_set["confidence"] == "exact"
    assert market_set["matched_row_team1"] == "Team WE"
    assert market_set["matched_row_team2"] == "ThunderTalk Gaming"
    assert any(
        offer["selection_key"] == "team_a" and offer["decimal_odds"] == 1.45
        for offer in market_set["offers"]
    )
    assert any(
        offer["selection_key"] == "team_b" and offer["decimal_odds"] == 2.66
        for offer in market_set["offers"]
    )


def test_resolve_match_odds_uses_market_catalog_for_real_card_layout() -> None:
    catalog = _build_market_catalog_from_page_text(THUNDERPICK_CARD_TEXT)

    resolution = resolve_match_odds(
        "Team WE",
        "ThunderTalk Gaming",
        odds_list=[],
        market_catalog=catalog,
    )

    assert resolution["odds1"] == 1.45
    assert resolution["odds2"] == 2.66
    assert resolution["odds_source_kind"] == "market_catalog_fallback"
    assert resolution["odds_source_status"] == "available"
    assert resolution["has_match_winner_offer"] is True


def test_find_market_set_matches_accented_team_names_after_normalization() -> None:
    catalog = _build_market_catalog_from_page_text("Fluxo W7M 1.50 vs 2.40 Leviatán")

    market_set = find_market_set_for_match("Fluxo W7M", "Leviatan Esports", catalog)

    assert market_set["matched"] is True
    assert market_set["confidence"] in {"exact", "substring"}
    assert market_set["matched_row_team1"] == "Fluxo W7M"
    assert market_set["matched_row_team2"] == "Leviatán"


def test_extract_from_page_text_strips_inline_live_badges_from_team_names() -> None:
    rows = _extract_from_page_text(
        """
        Movistar KOI 1.28 vs 3.30 Fnatic LIVE
        Fluxo W7M 1.50 vs 2.40 Leviatán LIVE
        """
    )

    assert rows == [
        {"team1": "Movistar KOI", "team2": "Fnatic", "odds1": 1.28, "odds2": 3.3},
        {"team1": "Fluxo W7M", "team2": "Leviatán", "odds1": 1.5, "odds2": 2.4},
    ]


def test_extract_from_page_text_strips_region_prefixes_and_rejects_midword_captures() -> None:
    rows = _extract_from_page_text(
        """
        China Team WE 1.45 vs 2.66 ThunderTalk Gaming
        China Ninjas in Pyjamas 1.49 vs 2.55 OMG
        eam WE 1.45 vs 2.66 ThunderTalk Gaming
        K Gaming 2.50 vs 1.48 Team Heretics
        """
    )

    assert rows == [
        {"team1": "Team WE", "team2": "ThunderTalk Gaming", "odds1": 1.45, "odds2": 2.66},
        {"team1": "Ninjas in Pyjamas", "team2": "OMG", "odds1": 1.49, "odds2": 2.55},
    ]


def test_extract_from_page_text_reports_rejection_diagnostics_for_polluted_rows() -> None:
    diagnostics: dict[str, object] = {}

    rows = _extract_from_page_text(
        """
        China Team WE 1.45 vs 2.66 ThunderTalk Gaming
        eam WE 1.45 vs 2.66 ThunderTalk Gaming
        K Gaming 2.50 vs 1.48 Team Heretics
        """,
        diagnostics=diagnostics,
    )

    assert rows == [
        {"team1": "Team WE", "team2": "ThunderTalk Gaming", "odds1": 1.45, "odds2": 2.66},
    ]
    assert diagnostics["accepted_count"] == 1
    assert diagnostics["rejected_count"] == 2
    assert diagnostics["raw_candidate_count"] >= 3
    assert diagnostics["sample_matches"] == ["Team WE vs ThunderTalk Gaming"]
    assert diagnostics["sample_rejections"] == [
        {"team1": "eam WE", "team2": "ThunderTalk Gaming", "reason": "midword_capture"},
        {"team1": "K Gaming", "team2": "Team Heretics", "reason": "single_letter_prefix"},
    ]


def test_build_market_catalog_ignores_polluted_rows_and_preserves_clean_pairs() -> None:
    catalog = _build_market_catalog_from_page_text(
        """
        China Team WE 1.45 vs 2.66 ThunderTalk Gaming
        eam WE 1.45 vs 2.66 ThunderTalk Gaming
        K Gaming 2.50 vs 1.48 Team Heretics
        2026 Spring SK Gaming 2.50 vs 1.48 Team Heretics
        Movistar KOI 1.28 vs 3.30 Fnatic LIVE
        2026 Spring Movistar KOI 1.28 vs 3.30 Fnatic
        2026 Split 1 paiN Gaming 2.40 vs 1.50 Keyd Stars
        2026 Split 1 Fluxo W7M 1.50 vs 2.40 Leviatán
        Fluxo W7M 1.50 vs 2.40 Leviatán LIVE
        """
    )

    assert [
        (match["team1"], match["team2"])
        for match in catalog["matches"]
    ] == [
        ("Team WE", "ThunderTalk Gaming"),
        ("SK Gaming", "Team Heretics"),
        ("Movistar KOI", "Fnatic"),
        ("paiN Gaming", "Keyd Stars"),
        ("Fluxo W7M", "Leviatán"),
    ]


def test_resolve_match_odds_handles_polluted_realistic_text_blob() -> None:
    catalog = _build_market_catalog_from_page_text(
        """
        China Team WE 1.45 vs 2.66 ThunderTalk Gaming
        2026 Spring Movistar KOI 1.28 vs 3.30 Fnatic LIVE
        2026 Split 1 Fluxo W7M 1.50 vs 2.40 Leviatán LIVE
        """
    )

    movistar = resolve_match_odds("Movistar KOI", "Fnatic", odds_list=[], market_catalog=catalog)
    fluxo = resolve_match_odds("Fluxo W7M", "Leviatan Esports", odds_list=[], market_catalog=catalog)

    assert movistar["odds1"] == 1.28
    assert movistar["odds2"] == 3.3
    assert movistar["odds_source_kind"] == "market_catalog_fallback"
    assert fluxo["odds1"] == 1.5
    assert fluxo["odds2"] == 2.4
    assert fluxo["odds_source_kind"] == "market_catalog_fallback"


def test_extract_from_page_text_strips_leading_season_metadata_from_team_names() -> None:
    rows = _extract_from_page_text(
        """
        2026 Spring SK Gaming 2.50 vs 1.48 Team Heretics
        2026 Spring Movistar KOI 1.28 vs 3.30 Fnatic
        2026 Split 1 paiN Gaming 2.40 vs 1.50 Keyd Stars
        2026 Split 1 Fluxo W7M 1.50 vs 2.40 Leviatán
        """
    )

    assert rows == [
        {"team1": "SK Gaming", "team2": "Team Heretics", "odds1": 2.5, "odds2": 1.48},
        {"team1": "Movistar KOI", "team2": "Fnatic", "odds1": 1.28, "odds2": 3.3},
        {"team1": "paiN Gaming", "team2": "Keyd Stars", "odds1": 2.4, "odds2": 1.5},
        {"team1": "Fluxo W7M", "team2": "Leviatán", "odds1": 1.5, "odds2": 2.4},
    ]
