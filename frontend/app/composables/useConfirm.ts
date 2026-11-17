import { AppConfirmModal } from '#components'

type ConfirmOptions = {
  title: string
  description?: string
  confirmLabel?: string
  color?: 'error' | 'warning' | 'primary'
  icon?: string
}

/** Styled replacement for window.confirm(): `if (!await confirm({ title: 'Excluir?' })) return` */
export function useConfirm() {
  const modal = useOverlay().create(AppConfirmModal)
  return async (options: ConfirmOptions): Promise<boolean> => (await modal.open(options).result) === true
}
