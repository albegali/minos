// The unit tests assert the Italian labels (the reference catalogue), whatever the language
// of the machine running them.
import { useLang } from './i18n'

useLang.setState({ lang: 'it' })
