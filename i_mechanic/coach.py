#!/usr/bin/env python3
"""
I, Mechanic — ACC MoTeC telemetry setup coach

Usage:
    python -m i_mechanic.coach <path/to/file.ld> ["your driver feedback text"]

What it does:
  1. Parses an ACC MoTeC .ld file with the open-source `ldparser`.
  2. Aligns all channels onto a common time grid over the "driving" region.
  3. Computes a setup-relevant telemetry brief (tire temps/pressures, brake temps,
     throttle/brake/steering behaviour, TC/ABS usage, wheel slip, suspension
     travel & bumpstops, and an understeer/oversteer proxy).
  4. Sends the brief + the driver's feedback to an AI race-engineer (LLM) that
     returns structured, explainable setup-change suggestions.

Telemetry parsing runs locally. AI suggestions are sent to the selected local or hosted provider using Python's standard-library HTTP client.
"""
import sys, os, json, argparse, datetime, importlib
try:
    # Import by name so the script can provide an actionable message when the
    # optional runtime dependency is not installed in the selected interpreter.
    np = importlib.import_module("numpy")
except ImportError as exc:
    raise SystemExit(
        "NumPy is required. Install it in this Python environment with "
        "'python -m pip install numpy'."
    ) from exc
l = importlib.import_module("ldparser.ldparser")

# ----------------------------------------------------------------------------
# Channel groups (ACC MoTeC export names)
# ----------------------------------------------------------------------------
CORNERS = ["LF", "RF", "LR", "RR"]
TYRE_TEMP  = {c: f"TYRE_TAIR_{c}" for c in CORNERS}      # core/air temp
TYRE_PRES  = {c: f"TYRE_PRESS_{c}" for c in CORNERS}
BRAKE_TEMP = {c: f"BRAKE_TEMP_{c}" for c in CORNERS}
SUS_TRAV   = {c: f"SUS_TRAVEL_{c}" for c in CORNERS}
WHEEL_SPD  = {c: f"WHEEL_SPEED_{c}" for c in CORNERS}
BUMP_FORCE = {c: f"BUMPSTOP_FORCE_{c}" for c in CORNERS}

SPEED_CH, THROTTLE_CH, BRAKE_CH, STEER_CH, RPMS_CH, GEAR_CH = (
    "SPEED", "THROTTLE", "BRAKE", "STEERANGLE", "RPMS", "GEAR")
GLAT_CH, ROTY_CH, TC_CH, ABS_CH = "G_LAT", "ROTY", "TC", "ABS"

REQUIRED_CHANNELS = [
    SPEED_CH, THROTTLE_CH, BRAKE_CH, STEER_CH, RPMS_CH,
    GLAT_CH, ROTY_CH, TC_CH, ABS_CH,
    *TYRE_TEMP.values(), *TYRE_PRES.values(),
    *BRAKE_TEMP.values(), *SUS_TRAV.values(),
    *WHEEL_SPD.values(), *BUMP_FORCE.values(),
]


def channel_inventory(chans):
    """Describe available channels so conclusions can carry data-quality context."""
    inventory = {}
    for name, channel in sorted(chans.items()):
        samples = len(channel.data)
        inventory[name] = {
            "samples": samples,
            "frequency_hz": round(float(channel.freq), 3),
            "duration_s": round(samples / channel.freq, 3) if channel.freq else 0.0,
        }
    return inventory


def data_quality(chans, required_channels):
    inventory = channel_inventory(chans)
    missing = [name for name in required_channels if name not in chans]
    frequencies = [item["frequency_hz"] for item in inventory.values()]
    durations = [item["duration_s"] for item in inventory.values()]
    return {
        "channel_count": len(inventory),
        "available_channels": sorted(inventory),
        "missing_required_channels": missing,
        "sample_rates_hz": {
            "min": min(frequencies) if frequencies else 0.0,
            "max": max(frequencies) if frequencies else 0.0,
        },
        "channel_duration_s": {
            "min": round(min(durations), 3) if durations else 0.0,
            "max": round(max(durations), 3) if durations else 0.0,
        },
        "status": "incomplete" if missing else "ready",
        "confidence": "low" if missing else "provisional",
    }


def robust(arr, q=99.0):
    """Mean ignoring the top/bottom outliers (MoTeC data has spikes)."""
    if len(arr) == 0:
        return float("nan")
    lo, hi = np.percentile(arr, [1.0, q])
    m = arr[(arr >= lo) & (arr <= hi)]
    return float(m.mean()) if len(m) else float(arr.mean())


def load(ld_path):
    data = l.ldData.fromfile(ld_path)
    return {c.name: c for c in data.channs}, data.head


def time_axis(ch):
    return np.arange(len(ch.data), dtype=float) / ch.freq


def resample(chans, name, t_grid):
    """Interpolate a channel onto t_grid (clamped to its own span)."""
    ch = chans[name]
    t = time_axis(ch)
    d = np.asarray(ch.data, dtype=float)
    return np.interp(t_grid, t, d, left=d[0], right=d[-1])


def build_brief(ld_path):
    chans, head = load(ld_path)
    quality = data_quality(chans, REQUIRED_CHANNELS)
    if quality["missing_required_channels"]:
        return {
            "error": "Telemetry file is missing required channels.",
            "data_quality": quality,
        }
    # Master clock from SPEED (60 Hz). Driving region = where speed > 2 m/s.
    sp = np.asarray(chans[SPEED_CH].data, dtype=float)
    tsp = time_axis(chans[SPEED_CH])
    moving = sp > 2.0
    if not moving.any():
        return {"error": "No driving data (speed never exceeds 2 m/s) in this file."}
    idx = np.nonzero(moving)[0]
    t0, t1 = tsp[idx[0]], tsp[idx[-1]]
    # Common 20 Hz grid over the driving window
    t_grid = np.arange(t0, t1, 1 / 20.0)

    def rs(name):
        return resample(chans, name, t_grid)

    sp_g = rs(SPEED_CH)
    th_g = rs(THROTTLE_CH)
    br_g = rs(BRAKE_CH)
    st_g = rs(STEER_CH)
    rpms_g = rs(RPMS_CH)
    glat_g = np.abs(rs(GLAT_CH))
    roty_g = rs(ROTY_CH)
    tc_g = rs(TC_CH)
    abs_g = rs(ABS_CH)

    brief = {
        "file": os.path.basename(ld_path),
        "venue": getattr(head, "venue", ""),
        "event_vehicle": str(getattr(head, "event", "")),
        "datetime": str(getattr(head, "datetime", "")),
        "driving_time_s": round(t1 - t0, 1),
        "driving_segments": int(np.sum(np.diff(np.concatenate([[0], moving.astype(int)])) == 1)),
        "speed_kmh_avg": round(robust(sp_g) * 3.6, 1),
        "speed_kmh_max": round(np.percentile(sp_g, 99) * 3.6, 1),
        "data_quality": quality,
    }

    # --- Tyres ---
    tyres = {}
    for c in CORNERS:
        tt = rs(TYRE_TEMP[c])
        tp = rs(TYRE_PRES[c])
        tyres[c] = {
            "temp_c_mean": round(robust(tt), 1),
            "temp_c_max": round(np.percentile(tt, 99), 1),
            "press_psi_mean": round(robust(tp), 2),
            "press_psi_start": round(float(tp[np.percentile(np.arange(len(tp)), 5).astype(int)] if len(tp) else 0), 2),
            "press_psi_end": round(float(tp[np.percentile(np.arange(len(tp)), 95).astype(int)] if len(tp) else 0), 2),
        }
    brief["tyres"] = tyres

    # Front/rear axle temp balance
    ftemp = np.mean([tyres[c]["temp_c_mean"] for c in ["LF", "RF"]])
    rtemp = np.mean([tyres[c]["temp_c_mean"] for c in ["LR", "RR"]])
    brief["temp_balance"] = {
        "front_avg_c": round(ftemp, 1), "rear_avg_c": round(rtemp, 1),
        "front_rear_delta_c": round(ftemp - rtemp, 1),
        "left_right_front_delta_c": round(tyres["LF"]["temp_c_mean"] - tyres["RF"]["temp_c_mean"], 1),
        "left_right_rear_delta_c": round(tyres["LR"]["temp_c_mean"] - tyres["RR"]["temp_c_mean"], 1),
    }

    # --- Brakes ---
    brief["brake_temps_c"] = {c: round(robust(rs(BRAKE_TEMP[c])), 0) for c in CORNERS}

    # --- Driver inputs ---
    brief["inputs"] = {
        "throttle_avg_pct": round(robust(th_g), 1),
        "throttle_wot_pct": round(float(np.mean(th_g > 95) * 100), 1),
        "throttle_smoothness_std": round(float(np.std(th_g)), 1),
        "brake_avg_pct": round(robust(br_g), 1),
        "brake_peak_pct": round(float(np.percentile(br_g, 99)), 1),
        "steer_abs_avg_deg": round(robust(np.abs(st_g)), 1),
        "steer_peak_deg": round(float(np.percentile(np.abs(st_g), 99)), 1),
        "rpm_avg": round(robust(rpms_g), 0),
        "rpm_max": round(float(np.percentile(rpms_g, 99)), 0),
    }

    # --- TC / ABS ---
    brief["electronics"] = {
        "tc_active_pct": round(float(np.mean(tc_g > 0.05) * 100), 1),
        "abs_active_pct": round(float(np.mean(abs_g > 0.05) * 100), 1),
    }

    # --- Wheel slip (rear vs front during acceleration) ---
    wsp = {c: rs(WHEEL_SPD[c]) for c in CORNERS}
    accel = th_g > 80
    front_spd = (wsp["LF"] + wsp["RF"]) / 2
    rear_spd = (wsp["LR"] + wsp["RR"]) / 2
    slip = rear_spd - front_spd
    brief["wheel_slip"] = {
        "rear_over_front_under_accel_kmh": round(float(np.mean(slip[accel]) * 3.6), 1) if accel.any() else 0.0,
        "peak_rear_slip_kmh": round(float(np.percentile(slip[accel], 95) * 3.6), 1) if accel.any() else 0.0,
        "lf_vs_rf_speed_diff_kmh": round(float(np.mean(np.abs(wsp["LF"] - wsp["RF"])) * 3.6), 2),
    }

    # --- Suspension & bumpstops ---
    sus = {}
    for c in CORNERS:
        s = rs(SUS_TRAV[c])
        bf = rs(BUMP_FORCE[c])
        sus[c] = {
            "travel_min_mm": round(float(np.percentile(s, 1)), 1),
            "travel_max_mm": round(float(np.percentile(s, 99)), 1),
            "travel_range_mm": round(float(np.percentile(s, 99) - np.percentile(s, 1)), 1),
            "bumpstop_hits_pct": round(float(np.mean(bf > 0.5) * 100), 1),
        }
    brief["suspension"] = sus

    # --- Understeer / oversteer proxy ---
    # Understeer: high steering demand vs low actual yaw rate.
    # Slip-angle proxy: steering angle (deg) vs yaw rate (rad/s).
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.abs(st_g) / (np.abs(roty_g) + 1e-3)
    ratio = ratio[np.isfinite(ratio)]
    brief["balance_proxy"] = {
        "steer_to_yaw_ratio_mean": round(float(np.percentile(ratio, 50)), 1) if len(ratio) else 0.0,
        "cornering_g_lat_mean": round(robust(glat_g), 2),
        "cornering_g_lat_peak": round(float(np.percentile(glat_g, 99)), 2),
    }
    return brief


# ----------------------------------------------------------------------------
# AI suggestions (LLM) step
# ----------------------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "session_summary": {"type": "string", "maxLength": 2000},
        "issues_found": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "issue": {"type": "string", "maxLength": 500},
                    "telemetry_evidence": {"type": "string", "maxLength": 800},
                },
                "required": ["issue", "telemetry_evidence"],
            },
        },
        "setup_changes": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "parameter": {"type": "string", "maxLength": 200},
                    "change_direction": {"type": "string", "maxLength": 200},
                    "magnitude_hint": {"type": "string", "maxLength": 200},
                    "addresses_symptom": {"type": "string", "maxLength": 500},
                    "telemetry_evidence": {"type": "string", "maxLength": 800},
                    "reasoning": {"type": "string", "maxLength": 800},
                    "expected_side_effects": {"type": "string", "maxLength": 500},
                    "test_next": {"type": "string", "maxLength": 500},
                },
                "required": ["parameter", "change_direction", "magnitude_hint", "addresses_symptom", "telemetry_evidence", "reasoning", "expected_side_effects", "test_next"],
            },
        },
    },
    "required": ["session_summary", "issues_found", "setup_changes"],
}

INSTRUCTION = (
    "You are an expert GT3 race engineer for Assetto Corsa Competizione. "
    "You are given a JSON telemetry brief parsed from a driver's MoTeC .ld export, "
    "plus the driver's own subjective feedback. "
    "Diagnose what the car is doing from the data, reconcile it with the driver feedback, "
    "and produce 2-4 CONSERVATIVE, explainable setup changes. "
    "Each change must state the parameter, the direction to move it, a rough magnitude, "
    "which symptom it addresses, the telemetry evidence supporting it, the reasoning, "
    "likely side effects, and what to test next. "
    "Prioritise the highest-impact, lowest-risk changes. Do not invent numbers not supported by the brief. "
    "If the session is too short to be conclusive, say so and recommend what extra data to gather."
)



PROVIDERS = {
    "lmstudio": {
        "base_url_env": "LMSTUDIO_BASE_URL",
        "base_url": "http://localhost:1234/v1",
        "model_env": "LMSTUDIO_MODEL",
        "model": "local-model",
        "api_key_env": "LMSTUDIO_API_KEY",
        "kind": "openai",
    },
    "ollama": {
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url": "http://localhost:11434",
        "model_env": "OLLAMA_MODEL",
        "model": "llama3.2",
        "api_key_env": "OLLAMA_API_KEY",
        "kind": "ollama",
    },
    "openai": {
        "base_url_env": "OPENAI_BASE_URL",
        "base_url": "https://api.openai.com/v1",
        "model_env": "OPENAI_MODEL",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "kind": "openai",
    },
    "openrouter": {
        "base_url_env": "OPENROUTER_BASE_URL",
        "base_url": "https://openrouter.ai/api/v1",
        "model_env": "OPENROUTER_MODEL",
        "model": "openai/gpt-4o-mini",
        "api_key_env": "OPENROUTER_API_KEY",
        "kind": "openai",
    },
    "groq": {
        "base_url_env": "GROQ_BASE_URL",
        "base_url": "https://api.groq.com/openai/v1",
        "model_env": "GROQ_MODEL",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
        "kind": "openai",
    },
    "together": {
        "base_url_env": "TOGETHER_BASE_URL",
        "base_url": "https://api.together.xyz/v1",
        "model_env": "TOGETHER_MODEL",
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "api_key_env": "TOGETHER_API_KEY",
        "kind": "openai",
    },
}


def provider_defaults(provider):
    """Return environment-aware URL, model, and credential setting for a provider."""
    try:
        config = PROVIDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported AI provider: {provider}") from exc
    return {
        "base_url": os.environ.get(config["base_url_env"], config["base_url"]),
        "model": os.environ.get(config["model_env"], config["model"]),
        "api_key_env": config["api_key_env"],
    }


def list_models(provider="lmstudio", base_url=None):
    """Return models exposed by a provider, or raise an actionable error."""
    import urllib.error
    import urllib.request

    config = PROVIDERS.get(provider)
    if config is None:
        raise ValueError(f"Unsupported AI provider: {provider}")
    defaults = provider_defaults(provider)
    endpoint = (base_url or defaults["base_url"]).rstrip("/")
    if config["kind"] == "ollama":
        request_url = f"{endpoint}/api/tags"
    else:
        request_url = f"{endpoint}/models"

    headers = {}
    api_key = os.environ.get(config["api_key_env"])
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(request_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_data = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{provider} model-list request returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to {provider} at {endpoint}. "
            "Check that the service is reachable and verify its URL."
        ) from exc

    if config["kind"] == "ollama":
        return [model["name"] for model in response_data.get("models", []) if model.get("name")]
    return [model["id"] for model in response_data.get("data", []) if model.get("id")]


def run_engineer(brief, feedback, model=None, base_url=None, provider="lmstudio", project_context=None):
    import urllib.error
    import urllib.request

    item = json.dumps({
        "telemetry_brief": brief,
        "driver_feedback": feedback,
        "project_context": project_context,
    })
    config = PROVIDERS.get(provider)
    if config is None:
        raise ValueError(f"Unsupported AI provider: {provider}")
    defaults = provider_defaults(provider)
    selected_model = model or defaults["model"]
    messages = [
        {"role": "system", "content": INSTRUCTION},
        {"role": "user", "content": item},
    ]
    if config["kind"] == "ollama":
        endpoint = (base_url or defaults["base_url"]).rstrip("/")
        request_url = f"{endpoint}/api/chat"
        payload = {
            "model": selected_model,
            "messages": messages,
            "format": SCHEMA,
            "stream": False,
            "options": {"num_predict": int(os.environ.get("AI_MAX_OUTPUT_TOKENS", "4096"))},
        }
    else:
        endpoint = (base_url or defaults["base_url"]).rstrip("/")
        request_url = f"{endpoint}/chat/completions"
        payload = {
            "model": selected_model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "race_engineer_assessment", "schema": SCHEMA},
            },
            "max_tokens": int(os.environ.get("AI_MAX_OUTPUT_TOKENS", "4096")),
        }
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(config["api_key_env"])
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response_data = _post_engineer_request(request_url, payload, headers)
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as structured_error:
        if config["kind"] == "ollama":
            raise
        # Some providers or models reject structured output; retry with a schema prompt.
        fallback_messages = [
            {"role": "system", "content": INSTRUCTION + " Return ONLY valid JSON matching this schema: " + json.dumps(SCHEMA)},
            {"role": "user", "content": item},
        ]
        fallback_payload = {
            "model": selected_model,
            "messages": fallback_messages,
            "max_tokens": int(os.environ.get("AI_MAX_OUTPUT_TOKENS", "4096")),
        }
        try:
            response_data = _post_engineer_request(request_url, fallback_payload, headers)
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as fallback_error:
            raise RuntimeError(
                f"{provider} structured output failed ({structured_error}); "
                f"plain-JSON fallback also failed ({fallback_error})."
            ) from fallback_error

    if config["kind"] == "ollama":
        content = response_data["message"]["content"]
    else:
        content = response_data["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return _parse_json_response(content)


def _post_engineer_request(request_url, payload, headers):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(os.environ.get("AI_REQUEST_TIMEOUT", "300"))) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to the AI server: {exc}") from exc


def _parse_json_response(content):
    """Accept JSON wrapped in a markdown fence or brief model preamble."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ld")
    ap.add_argument("feedback", nargs="?", default="No specific feedback given. Diagnose from telemetry alone and flag any balance/pressure/temperature issues.")
    ap.add_argument("--no-llm", action="store_true", help="Only print the telemetry brief, skip the LLM step.")
    ap.add_argument(
        "--provider", choices=tuple(PROVIDERS), default="lmstudio",
        help="AI provider to use (default: lmstudio).",
    )
    ap.add_argument("--model", help="Model identifier; defaults to the selected provider's *_MODEL environment variable.")
    ap.add_argument("--base-url", help="AI server URL; defaults to the selected provider's configured URL.")
    args = ap.parse_args()

    brief = build_brief(args.ld)
    print("=" * 70)
    print("TELEMETRY BRIEF")
    print("=" * 70)
    print(json.dumps(brief, indent=2, ensure_ascii=False))

    if "error" in brief:
        print("\n[brief error]", brief["error"])
        return

    if args.no_llm:
        return

    print("\n" + "=" * 70)
    print("I, MECHANIC — SETUP SUGGESTIONS")
    print("=" * 70)
    try:
        result = run_engineer(brief, args.feedback, args.model, args.base_url, args.provider)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[LLM step failed: {e}]")
        print("Run with --no-llm to get just the brief. The brief above is the LLM-ready input.")


if __name__ == "__main__":
    main()
