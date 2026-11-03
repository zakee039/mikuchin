import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) {
        f.reader(Charsets.UTF_8).use { load(it) }
    }
}
val ksPath = System.getenv("MIKUCHIN_KEYSTORE_PATH") ?: localProps.getProperty("sign.storeFile", "")
val ksPass = System.getenv("MIKUCHIN_KEYSTORE_PASSWORD") ?: localProps.getProperty("sign.storePassword", "")
val ksAlias = System.getenv("MIKUCHIN_KEY_ALIAS") ?: localProps.getProperty("sign.keyAlias", "")
val ksKeyPass = System.getenv("MIKUCHIN_KEY_PASSWORD") ?: localProps.getProperty("sign.keyPassword", "")
val hasReleaseSigning = ksPath.isNotBlank() && File(ksPath).exists()

android {
    namespace = "com.mikuchin.client"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.mikuchin.client"
        minSdk = 26
        targetSdk = 34
        versionCode = 204
        versionName = "0.2.4"
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = File(ksPath)
                storePassword = ksPass
                keyAlias = ksAlias
                keyPassword = ksKeyPass
            }
        }
    }

    buildTypes {
        debug {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        release {
            isMinifyEnabled = false
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    implementation(files("libs/tsnetbridge.aar"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("androidx.webkit:webkit:1.11.0")
}
