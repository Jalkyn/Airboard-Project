import { motion } from 'motion/react'
import TopBar from '../TopBar'
import { FileText, Download, Calendar, TrendingUp, Clock, Loader2, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select'
import { useState } from 'react'
import { toast } from 'sonner'
import { useDataDir } from '../../contexts/DataDirContext'
import { getApiUrl, API_ENDPOINTS } from '../../lib/api-config'

type Page = 'home' | 'dashboard' | 'map' | 'rapports' | 'about-us' | 'how-it-works'

interface RapportsPageProps {
  onNavigate?: (page: Page) => void
}

export default function RapportsPage({ onNavigate }: RapportsPageProps = {}) {
  const { dataDir } = useDataDir()
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [periodeType, setPeriodeType] = useState('Journalier')
  const [audience, setAudience] = useState('Opérateurs Terrain')
  const [isGenerating, setIsGenerating] = useState(false)
  const [reportGenerated, setReportGenerated] = useState(false)
  const [reportContent, setReportContent] = useState('')
  const [windRoseFig, setWindRoseFig] = useState<any>(null)
  const [additionalGraphs, setAdditionalGraphs] = useState<any>({})
  const [errorMessage, setErrorMessage] = useState('')
  const [fileInfo, setFileInfo] = useState<{name?: string, total_rows?: number, filtered_rows?: number}>({})

  const handleGenerateReport = async () => {
    if (!startDate || !endDate) {
      toast.error('Veuillez sélectionner les dates de début et de fin')
      return
    }

    if (new Date(startDate) > new Date(endDate)) {
      toast.error('La date de début doit être antérieure à la date de fin')
      return
    }

    setIsGenerating(true)
    setReportGenerated(false)
    setErrorMessage('')
    setFileInfo({})

    try {
      const response = await fetch(getApiUrl(API_ENDPOINTS.REPORTS_GENERATE), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          date_debut: startDate,
          date_fin: endDate,
          periode_type: periodeType,
          audience: audience,
          // Ne pas envoyer "data" car c'est le dossier par défaut
          ...(dataDir && dataDir.trim() !== '' && dataDir.trim().toLowerCase() !== 'data' && { data_dir: dataDir }),
        }),
      })

      const data = await response.json()

      if (data.status === 'error' || response.status !== 200) {
        setErrorMessage(data.error || 'Erreur lors de la génération du rapport')
        setFileInfo({
          name: data.file_name,
          total_rows: data.total_rows,
          filtered_rows: data.filtered_rows || 0
        })
        toast.error(data.error || 'Erreur lors de la génération du rapport')
        setIsGenerating(false)
        return
      }

      // Stocker les résultats
      setReportContent(data.report_markdown || '')
      setWindRoseFig(data.wind_rose_fig)
      setAdditionalGraphs(data.additional_graphs || {})
      setFileInfo({
        name: data.file_name,
        total_rows: data.total_rows,
        filtered_rows: data.filtered_rows
      })
      setReportGenerated(true)
      toast.success('Rapport généré avec succès!')
    } catch (error) {
      console.error('Erreur:', error)
      setErrorMessage('Erreur de connexion au serveur. Assurez-vous que le serveur Flask est démarré.')
      toast.error('Erreur de connexion au serveur')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleExportPDF = async () => {
    if (!reportContent) {
      toast.error('Aucun rapport à exporter')
      return
    }

    try {
      toast.info('Génération du PDF en cours...')
      const response = await fetch(getApiUrl(API_ENDPOINTS.REPORTS_GENERATE_PDF), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          report_markdown: reportContent,
          wind_rose_fig: windRoseFig,
          additional_graphs: additionalGraphs,
        }),
      })

      console.log('Response status:', response.status)
      console.log('Response headers:', response.headers.get('content-type'))

      if (response.ok) {
        // Vérifier que c'est bien un PDF
        const contentType = response.headers.get('content-type')
        if (contentType && contentType.includes('application/pdf')) {
          const blob = await response.blob()
          console.log('Blob size:', blob.size, 'bytes')
          
          if (blob.size === 0) {
            toast.error('Le PDF généré est vide')
            return
          }

          const url = window.URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `rapport_meteo_ocp_${new Date().toISOString().split('T')[0]}.pdf`
          a.style.display = 'none'
          document.body.appendChild(a)
          a.click()
          
          // Nettoyer après un court délai
          setTimeout(() => {
            window.URL.revokeObjectURL(url)
            document.body.removeChild(a)
          }, 100)
          
          toast.success('PDF généré et téléchargé avec succès!')
        } else {
          // Si ce n'est pas un PDF, essayer de lire comme JSON pour voir l'erreur
          const text = await response.text()
          console.error('Réponse non-PDF:', text)
          try {
            const data = JSON.parse(text)
            toast.error(data.error || 'Erreur lors de la génération du PDF')
          } catch {
            toast.error('Erreur: Le serveur n\'a pas retourné un PDF valide')
          }
        }
      } else {
        // Essayer de lire l'erreur JSON
        try {
          const data = await response.json()
          console.error('Erreur serveur:', data)
          toast.error(data.error || 'Erreur lors de la génération du PDF')
        } catch {
          const text = await response.text()
          console.error('Erreur serveur (texte):', text)
          toast.error(`Erreur ${response.status}: ${text}`)
        }
      }
    } catch (error) {
      console.error('Erreur:', error)
      toast.error(`Erreur lors de la génération du PDF: ${error instanceof Error ? error.message : 'Erreur inconnue'}`)
    }
  }

  return (
    <>
      <TopBar currentPage="rapports" onNavigate={onNavigate || (() => {})} />
      <div className="min-h-screen p-8 pt-24">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <h1 
            className="gradient-text mb-4"
            style={{ 
              fontFamily: 'var(--font-heading)',
              fontSize: 'clamp(2.5rem, 5vw, 4rem)',
              fontWeight: 800,
            }}
          >
            Générateur de rapports
          </h1>
          <p className="text-lg dark:text-white/70 text-[#1A2A23]/70" style={{ fontFamily: 'var(--font-body)' }}>
            Créez des rapports d'analyse personnalisés pour vos données environnementales
          </p>
        </motion.div>

        {/* Configuration Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          <Card className="glass-card p-8 mb-8">
            <div className="flex items-center gap-3 mb-6">
              <Calendar className="text-emerald-500" size={28} />
              <h2 
                className="text-2xl dark:text-white text-[#1A2A23]"
                style={{ fontFamily: 'var(--font-heading)' }}
              >
                Sélection de la période
              </h2>
            </div>

            <div className="grid md:grid-cols-2 gap-6 mb-6">
              {/* Start Date */}
              <div>
                <Label htmlFor="start-date" className="flex items-center gap-2 mb-2">
                  <Clock size={16} className="text-emerald-500" />
                  <span style={{ fontFamily: 'var(--font-heading)' }}>Date de début</span>
                </Label>
                <Input
                  id="start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="glass-card border-emerald-500/30 dark:text-white text-[#1A2A23]"
                />
              </div>

              {/* End Date */}
              <div>
                <Label htmlFor="end-date" className="flex items-center gap-2 mb-2">
                  <Clock size={16} className="text-emerald-500" />
                  <span style={{ fontFamily: 'var(--font-heading)' }}>Date de fin</span>
                </Label>
                <Input
                  id="end-date"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="glass-card border-emerald-500/30 dark:text-white text-[#1A2A23]"
                />
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-6 mb-8">
              {/* Period Type */}
              <div>
                <Label htmlFor="periode-type" className="flex items-center gap-2 mb-2">
                  <Calendar size={16} className="text-emerald-500" />
                  <span style={{ fontFamily: 'var(--font-heading)' }}>Type de rapport</span>
                </Label>
                <Select value={periodeType} onValueChange={setPeriodeType}>
                  <SelectTrigger className="glass-card border-emerald-500/30 dark:text-white text-[#1A2A23]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Journalier">Journalier</SelectItem>
                    <SelectItem value="Mensuel">Mensuel</SelectItem>
                    <SelectItem value="Annuel">Annuel</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Audience */}
              <div>
                <Label htmlFor="audience" className="flex items-center gap-2 mb-2">
                  <TrendingUp size={16} className="text-emerald-500" />
                  <span style={{ fontFamily: 'var(--font-heading)' }}>Audience</span>
                </Label>
                <Select value={audience} onValueChange={setAudience}>
                  <SelectTrigger className="glass-card border-emerald-500/30 dark:text-white text-[#1A2A23]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Opérateurs Terrain">Opérateurs Terrain</SelectItem>
                    <SelectItem value="Management">Management</SelectItem>
                    <SelectItem value="Ingénieurs">Ingénieurs</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Generate Button */}
            <motion.div
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Button
                onClick={handleGenerateReport}
                disabled={isGenerating || !startDate || !endDate}
                className="w-full h-14 bg-gradient-to-r from-[#0E6B57] via-[#2FA36F] to-[#0E6B57] text-white shadow-lg shadow-emerald-500/30 hover:shadow-emerald-500/50 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ 
                  fontFamily: 'var(--font-heading)',
                  fontSize: '1.1rem',
                  fontWeight: 700,
                }}
              >
                {isGenerating ? (
                  <>
                    <Loader2 size={22} className="mr-3 animate-spin" />
                    Génération en cours...
                  </>
                ) : (
                  <>
                    <FileText size={22} className="mr-3" />
                    Générer le rapport
                  </>
                )}
              </Button>
            </motion.div>
          </Card>
        </motion.div>

        {/* Error Display */}
        {errorMessage && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <Card className="glass-card p-8 border-red-500/50">
              <div className="flex items-start gap-3">
                <AlertCircle className="text-red-500 mt-1" size={24} />
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-red-500 mb-2">Erreur</h3>
                  <p className="text-red-400 dark:text-red-300 mb-4">{errorMessage}</p>
                  {fileInfo.name && (
                    <div className="text-sm text-muted-foreground">
                      <p>Fichier utilisé: <strong>{fileInfo.name}</strong></p>
                      {fileInfo.total_rows !== undefined && (
                        <p>Nombre total de lignes dans le fichier: <strong>{fileInfo.total_rows}</strong></p>
                      )}
                      {fileInfo.filtered_rows !== undefined && (
                        <p>Lignes correspondant à la plage de dates: <strong>{fileInfo.filtered_rows}</strong></p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </Card>
          </motion.div>
        )}

        {/* Report Display - Only Export Button */}
        {reportGenerated && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <Card className="glass-card p-8">
              <div className="flex flex-col items-center justify-center gap-6">
                <div className="flex items-center gap-3">
                  <FileText className="text-emerald-500" size={28} />
                  <h2 
                    className="text-2xl dark:text-white text-[#1A2A23]"
                    style={{ fontFamily: 'var(--font-heading)' }}
                  >
                    Rapport généré avec succès
                  </h2>
                </div>

                {fileInfo.name && (
                  <div className="text-sm text-muted-foreground text-center">
                    <p>Fichier utilisé: <strong>{fileInfo.name}</strong></p>
                    {fileInfo.filtered_rows !== undefined && (
                      <p>Données analysées: <strong>{fileInfo.filtered_rows}</strong> lignes</p>
                    )}
                  </div>
                )}

                <motion.div
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <Button
                    onClick={handleExportPDF}
                    className="flex items-center gap-2 bg-gradient-to-r from-[#0E6B57] via-[#2FA36F] to-[#0E6B57] text-white shadow-lg shadow-emerald-500/30 hover:shadow-emerald-500/50 transition-all duration-300 px-8 py-6 text-lg"
                    style={{ fontFamily: 'var(--font-heading)' }}
                  >
                    <Download size={22} />
                    Exporter en PDF
                  </Button>
                </motion.div>
              </div>
            </Card>
          </motion.div>
        )}
      </div>
    </>
  )
}