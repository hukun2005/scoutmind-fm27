/** 只读可视化接口（`/visualizations/*`）的类型。 */

/** 价值散点中的一个球员；只有身价非空才会出现。 */
export interface ValueScatterPoint {
  instance_id: number
  name: string
  age: number | null
  ca: number | null
  pa: number | null
  market_value: number | null
  club: string | null
  position: string | null
}

/** `GET /visualizations/value-scatter` 响应。 */
export interface ValueScatterResponse {
  points: ValueScatterPoint[]
  total: number
  with_value: number
  returned: number
  note: string
}

/** 单币种的资金流向。 */
export interface TransferFlowBucket {
  currency: string
  buy_total: number
  sell_total: number
  loan_in_fee: number
  loan_out_fee: number
  net: number
  counts: {
    permanent_buy: number
    permanent_sell: number
    loan_in: number
    loan_out: number
    free: number
  }
  unknown_fee: number
}

/** `GET /visualizations/transfer-flow` 响应。 */
export interface TransferFlowResponse {
  club: { id: number; name: string } | null
  currencies: TransferFlowBucket[]
  excluded: Record<string, number>
  note: string
}
