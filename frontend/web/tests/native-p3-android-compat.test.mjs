import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const root = new URL("../../android/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const activity = read("app/src/main/java/com/mikuchin/client/MainActivity.kt");
const preflight = read("app/src/main/java/com/mikuchin/client/ServerHealthPreflight.kt");
const tailscale = read("app/src/main/java/com/mikuchin/client/TailscaleController.kt");
const gradle = read("app/build.gradle.kts");
const manifest = read("app/src/main/AndroidManifest.xml");

test("Native Android health challenge is recognized before any API Key is sent", () => {
  assert.match(activity, /openMikuchinConnection\(mode, endpoint, "\/health", ""\)/);
  assert.match(activity, /ServerHealthPreflight\.accepts\(healthCode, healthChallenge\)/);
  assert.match(activity, /openMikuchinConnection\(\s*mode, endpoint, "\/v1\/strata\/sessions", key\)/);
  assert.match(preflight, /if \(status != 401/);
  assert.match(preflight, /Missing or invalid gateway API key/);
  assert.match(preflight, /error\.optString\("type"\) == "unauthorized"/);
  assert.doesNotMatch(activity, /healthCode !in 200\.\.299/);
});

test("Separate Native Android preview does not overwrite stable package or Tailnet state", () => {
  assert.match(gradle, /applicationId = "com\.mikuchin\.client"/);
  assert.match(gradle, /create\("nativePreview"\)/);
  assert.match(gradle, /applicationIdSuffix = "\.nativepreview"/);
  assert.match(gradle, /signingConfig = signingConfigs\.getByName\("debug"\)/);
  assert.match(manifest, /android:label="\$\{appLabel\}"/);
  assert.match(tailscale, /context\.packageName\.endsWith\("\.nativepreview"\)/);
  assert.match(tailscale, /"mikuchin-native-android"/);
});
