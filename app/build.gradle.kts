plugins {
    id("com.android.application")
}

android {
    namespace = "app.shieldcc"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.shieldcc"
        // Shield 2019 runs Android TV 11 (API 30)
        minSdk = 27
        targetSdk = 30
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
