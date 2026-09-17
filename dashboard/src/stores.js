import { writable } from 'svelte/store'

/** Currently selected time window in days (7 | 30 | 90 | custom) */
export const timeWindow = writable(30)

/** Current page name */
export const currentPage = writable('overview')

/** Active stage filter (set from Overview pie chart click) */
export const stageFilter = writable(null)

/** PR number to pre-select when navigating to the PRs page */
export const selectedPRNumber = writable(null)
