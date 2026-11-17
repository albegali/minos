import { Button, Menu, MenuItemRadio, MenuList, MenuPopover, MenuTrigger } from '@fluentui/react-components'
import { LocalLanguage20Regular } from '@fluentui/react-icons'

import { LANGUAGE_NAMES, LANGUAGES, type Lang, useI18n, useLang } from '../i18n'

/** Menu to switch the Studio language; each language is named in itself. */
export function LanguageSwitch() {
  const { lang, t } = useI18n()
  const setLang = useLang((s) => s.setLang)
  return (
    <Menu
      checkedValues={{ lang: [lang] }}
      onCheckedValueChange={(_, d) => {
        const next = d.checkedItems[0]
        if (next) setLang(next as Lang)
      }}
    >
      <MenuTrigger disableButtonEnhancement>
        <Button appearance="subtle" icon={<LocalLanguage20Regular />} aria-label={t('common.language')}>
          {lang.toUpperCase()}
        </Button>
      </MenuTrigger>
      <MenuPopover>
        <MenuList>
          {LANGUAGES.map((l) => (
            <MenuItemRadio key={l} name="lang" value={l} lang={l}>
              {LANGUAGE_NAMES[l]}
            </MenuItemRadio>
          ))}
        </MenuList>
      </MenuPopover>
    </Menu>
  )
}
