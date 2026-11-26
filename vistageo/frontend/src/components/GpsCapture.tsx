import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import { gpsQuality, isGpsPositionValid, type GpsLimits, type GpsPosition } from '../services/gpsCapture'
import { Button } from './Button'
import { SkeletonText } from './Skeleton'

type Props = {
  disabled: boolean
  onChange: (position: GpsPosition | null) => void
}

export type GpsCaptureHandle = { stop: () => void }

export const GpsCapture = forwardRef<GpsCaptureHandle, Props>(function GpsCapture({ disabled, onChange }, ref) {
  const [limits, setLimits] = useState<GpsLimits | null>(null)
  const [loadingConfig, setLoadingConfig] = useState(true)
  const [position, setPosition] = useState<GpsPosition | null>(null)
  const [status, setStatus] = useState('Preparando captura GPS...')
  const [searching, setSearching] = useState(false)
  const callback = useRef(onChange)
  const disabledRef = useRef(disabled)
  const watch = useRef<number | null>(null)
  const timer = useRef<number | null>(null)
  const expiration = useRef<number | null>(null)
  const generation = useRef(0)

  useEffect(() => { callback.current = onChange }, [onChange])
  useEffect(() => { disabledRef.current = disabled }, [disabled])

  const stop = () => {
    generation.current += 1
    if (watch.current !== null) navigator.geolocation.clearWatch(watch.current)
    if (timer.current !== null) window.clearTimeout(timer.current)
    watch.current = null
    timer.current = null
  }

  useImperativeHandle(ref, () => ({
    stop: () => {
      stop()
      if (expiration.current !== null) window.clearTimeout(expiration.current)
      expiration.current = null
    },
  }))

  const start = (config: GpsLimits) => {
    stop()
    if (expiration.current !== null) window.clearTimeout(expiration.current)
    setPosition(null)
    callback.current(null)
    if (!navigator.geolocation) {
      setSearching(false)
      setStatus('La ubicación no está disponible en este navegador o contexto seguro.')
      return
    }
    const current = generation.current
    const startedAt = Date.now()
    let best = Infinity
    setSearching(true)
    setStatus('Buscando ubicación; espera una señal más precisa.')
    timer.current = window.setTimeout(() => {
      if (generation.current !== current) return
      stop()
      setSearching(false)
      setStatus(best <= config.aceptable
        ? 'Búsqueda finalizada. Puedes confirmar esta medición o repetir la captura.'
        : 'Tiempo agotado. Comprueba la ubicación del dispositivo o repite la captura.')
    }, 30000)
    try {
      watch.current = navigator.geolocation.watchPosition(
      (result) => {
        if (generation.current !== current || !isGpsPositionValid(result, startedAt, Date.now())) return
        if (result.coords.accuracy >= best) return
        best = result.coords.accuracy
        const value = {
          latitude: result.coords.latitude, longitude: result.coords.longitude,
          accuracy: result.coords.accuracy, capturedAt: new Date(result.timestamp).toISOString(),
          acceptable: result.coords.accuracy <= config.aceptable,
        }
        setPosition(value)
        callback.current(value)
        if (expiration.current !== null) window.clearTimeout(expiration.current)
        expiration.current = window.setTimeout(() => {
          best = Infinity
          setPosition(null)
          callback.current(null)
          setStatus('La medición caducó. Espera una nueva ubicación o repite la captura.')
        }, Math.max(0, result.timestamp + 30000 - Date.now()))
        setStatus(value.acceptable
          ? 'Precisión aceptable; puedes confirmar o esperar una señal mejor.'
          : 'Mejorando la precisión; espera una señal aceptable.')
      },
      (error) => {
        if (generation.current !== current) return
        if (error.code === error.PERMISSION_DENIED) {
          stop()
          if (expiration.current !== null) window.clearTimeout(expiration.current)
          setPosition(null)
          callback.current(null)
          setSearching(false)
          setStatus('Permiso de ubicación denegado. Habilítalo en el navegador y en el dispositivo.')
        } else if (error.code === error.TIMEOUT) {
          stop()
          setSearching(false)
          setStatus(best <= config.aceptable
            ? 'Búsqueda finalizada. Puedes confirmar esta medición o repetir la captura.'
            : 'Tiempo agotado. Comprueba la ubicación del dispositivo o repite la captura.')
        } else {
          setStatus('Ubicación no disponible. Comprueba que esté activada y espera o repite la captura.')
        }
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 },
      )
    } catch (error) {
      stop()
      setSearching(false)
      setStatus(error instanceof Error ? `No se pudo iniciar el GPS: ${error.message}` : 'No se pudo iniciar el GPS.')
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    apiRequest<GpsLimits>('/configuracion-gps', { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return
        if (![value.excelente, value.buena, value.aceptable, value.baja].every(Number.isFinite)
          || !(0 < value.excelente && value.excelente < value.buena && value.buena < value.aceptable && value.aceptable < value.baja)) {
          throw new Error('Configuración GPS inválida.')
        }
        setLimits(value)
        if (!disabledRef.current) start(value)
        else setStatus('Selecciona repetir captura para iniciar el GPS.')
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setStatus(error instanceof Error ? error.message : 'No se pudo cargar la configuración GPS.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingConfig(false) })
    return () => {
      controller.abort(); stop()
      if (expiration.current !== null) window.clearTimeout(expiration.current)
    }
  }, [])

  useEffect(() => {
    if (disabled && watch.current !== null) {
      stop()
      setSearching(false)
      setStatus('Captura detenida.')
    }
  }, [disabled])

  return <div className="surface-inset space-y-2 p-4">
    {loadingConfig ? <div role="status" aria-label="Cargando configuración GPS"><SkeletonText lines={2} /></div> : <>
    <p role="status" className="text-sm">{status}</p>
    {position && limits && <>
      <p className="text-sm">{position.latitude}, {position.longitude} · Precisión estimada: {position.accuracy} m ({gpsQuality(position.accuracy, limits)})</p>
      {position.accuracy > limits.aceptable
        ? <p role="alert" className="text-sm text-amber-800">Precisión insuficiente. Espera o repite la captura; no se puede guardar este punto.</p>
        : <p className="text-sm text-slate-600">Precisión aceptable. Puedes confirmar o esperar una mejor señal.</p>}
    </>}
    {limits && <div className="flex flex-wrap gap-2">
      <Button type="button" variant="secondary" disabled={disabled} onClick={() => start(limits)}>{searching ? 'Reiniciar captura' : 'Repetir captura'}</Button>
      {searching && <Button type="button" variant="ghost" disabled={disabled} onClick={() => {
        stop(); if (expiration.current !== null) window.clearTimeout(expiration.current)
        setSearching(false); setPosition(null); callback.current(null); setStatus('Captura cancelada.')
      }}>Cancelar captura</Button>}
    </div>}
    </>}
  </div>
})
