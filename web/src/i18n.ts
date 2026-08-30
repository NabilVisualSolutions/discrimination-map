import i18n from "i18next"
import { initReactI18next } from "react-i18next"
import en from "./locales/en.json"
import de from "./locales/de.json"
import fr from "./locales/fr.json"
import ar from "./locales/ar.json"

export const LOCALES = ["en", "de", "fr", "ar"] as const
export type Locale = (typeof LOCALES)[number]
const RTL: Locale[] = ["ar"]

const stored = (typeof localStorage !== "undefined" && localStorage.getItem("lang")) as Locale | null
const urlLang = new URLSearchParams(location.search).get("lang") as Locale | null
const initial: Locale =
  urlLang && LOCALES.includes(urlLang)
    ? urlLang
    : stored && LOCALES.includes(stored)
      ? stored
      : "en"

void i18n.use(initReactI18next).init({
  resources: { en: { t: en }, de: { t: de }, fr: { t: fr }, ar: { t: ar } },
  lng: initial,
  fallbackLng: "en",
  ns: ["t"],
  defaultNS: "t",
  interpolation: { escapeValue: false },
})

export function applyLocale(l: Locale) {
  void i18n.changeLanguage(l)
  localStorage.setItem("lang", l)
  document.documentElement.lang = l
  document.documentElement.dir = RTL.includes(l) ? "rtl" : "ltr"
}
applyLocale(initial)

export default i18n
