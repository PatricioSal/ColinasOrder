/* ─── TypeScript Interfaces ─────────────────────────────────────────────── */

export interface WebUser {
  UserID: number;
  Email: string;
  DisplayName: string;
  Role: 'admin' | 'user';
  IsActive: boolean;
  CreatedAt: string;
  LastLoginAt: string | null;
}

export interface JWTPayload {
  userId: number;
  email: string;
  displayName: string;
  role: 'admin' | 'user';
}

export interface Customer {
  id: number;
  name: string;
  phone?: string;
  company?: string;
}

export interface Product {
  id: number;
  name: string;
  sku: string;
  price: number;
  uom: string;
  qtyPerCase: number;
}

export interface ParsedMessage {
  messageType: 'order' | 'non_order';
  companyName: string;
  items: ParsedItem[];
  specialInstructions: string | null;
  deliveryInfo: string | null;
}

export interface ParsedItem {
  name: string;
  qty: number;
  sku: string | null;
  uom: string;
  secondaryQty?: number;
}

export interface MatchedOrderLine {
  productId: number | null;
  itemName: string;
  originalName: string;
  sku: string;
  qty: number;
  uom: string;
  secondaryQty: number;
  price: number;
  total: number;
  notes: string;
  productUom?: string;
}

export interface PendingOrder {
  PendingOrderID: number;
  BatchID: string;
  CustomerID: number | null;
  CustomerName: string | null;
  RawMessage: string;
  SpecialInstructions: string | null;
  Status: string;
  NeedsReview: boolean;
  SubmitterName: string | null;
  CreatedAt: string;
  lines: PendingOrderLine[];
  customerDetails?: CustomerDetails | null;
}

export interface PendingOrderLine {
  LineID: number;
  ProductID: number | null;
  ProductName: string | null;
  SKU: string | null;
  OriginalName: string | null;
  QuantityCs: number;
  QuantityLbs: number;
  UnitPrice: number;
  UOM: string | null;
  LineNote: string | null;
  NeedsReview: boolean;
  total: number;
}

export interface CustomerDetails {
  name?: string;
  phone?: string;
  address1?: string;
  address2?: string;
  city?: string;
  state?: string;
  zipcode?: string;
  country?: string;
  paymentTerms?: string | number;
  deliveryTerms?: string | number;
  salesmanId?: string | number;
  deliveryNotes?: string;
  taxId?: string;
}

export interface RecentOrder {
  id: string;
  customer: string;
  product: string;
  quantity: number;
  status: string;
  needsReview: boolean;
  createdAt: string;
}

export interface DashboardStats {
  ordersToday: number;
  needsReview: number;
  customers: number;
  products: number;
}

export interface EditOrderPayload {
  batchId: string;
  lines: {
    lineId: number;
    qty?: number;
    secondaryQty?: number;
    productId?: number | null;
    lineNote?: string;
  }[];
  deletedLines: number[];
  specialInstructions?: string;
  customerOverrides?: Record<string, string> | null;
}
