import { PaperAccountCard, PaperPositionsTable, PaperTradesTable, PaperOrderForm } from '@/components/widgets/PaperPanel'

interface Props { projectId: string }

export function PaperTab({ projectId }: Props) {
  return (
    <div className="grid gap-3 p-3 auto-rows-min" style={{ gridTemplateColumns: '1fr 1fr' }}>
      <div className="col-span-2"><PaperAccountCard projectId={projectId} /></div>
      <PaperPositionsTable projectId={projectId} />
      <PaperOrderForm projectId={projectId} />
      <div className="col-span-2"><PaperTradesTable projectId={projectId} /></div>
    </div>
  )
}
