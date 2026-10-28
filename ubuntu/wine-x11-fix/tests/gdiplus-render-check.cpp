#include <windows.h>
#include <gdiplus.h>
#include <stdio.h>
#include <stdint.h>
#include <vector>
using namespace Gdiplus;
static uint32_t seed = 0x197fa32c;
static uint32_t next_pixel()
{
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}
static double now()
{
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return (double)t.QuadPart / f.QuadPart;
}
int main(int argc, char** argv)
{
    if (argc != 2)
        return 2;
    ULONG_PTR token;
    GdiplusStartupInput input;
    if (GdiplusStartup(&token, &input, NULL) != Ok)
        return 3;
    FILE* output = fopen(argv[1], "wb");
    if (!output)
        return 4;
    wchar_t module[MAX_PATH];
    GetModuleFileNameW(GetModuleHandleW(L"gdiplus.dll"), module, MAX_PATH);
    printf("module=%ls\n", module);
    const int w = 67, h = 53, dw = 179, dh = 151;
    std::vector<ARGB> bits(w * h);
    const float scales[] = { 0.5f, 1.0f, 1.25f, 1.5f, 2.0f, 2.7f };
    const InterpolationMode modes[]
        = { InterpolationModeNearestNeighbor, InterpolationModeBilinear, InterpolationModeHighQualityBicubic };
    const WrapMode wraps[] = { WrapModeClamp, WrapModeTileFlipXY };
    unsigned cases = 0;
    for (int alpha = 0; alpha < 2; alpha++) {
        for (int i = 0; i < w * h; i++)
            bits[i] = alpha ? next_pixel() : (next_pixel() | 0xff000000);
        Bitmap source(w, h, w * 4, PixelFormat32bppARGB, (BYTE*)bits.data());
        for (float scale : scales)
            for (InterpolationMode mode : modes)
                for (WrapMode wrap : wraps)
                    for (int offset = 0; offset < 2; offset++) {
                        Bitmap target(dw, dh, PixelFormat32bppARGB);
                        Graphics graphics(&target);
                        ImageAttributes attributes;
                        attributes.SetWrapMode(wrap, Color(0x5a1a6bc1), FALSE);
                        graphics.Clear(Color(0x734b5a6c));
                        graphics.SetInterpolationMode(mode);
                        if (offset) {
                            graphics.TranslateTransform(4.3f, 2.7f);
                            graphics.RotateTransform(3.0f);
                        }
                        Status status = graphics.DrawImage(&source, RectF(2.0f, 3.0f, w * scale, h * scale), -1.0f,
                            -1.0f, w + 2.0f, h + 2.0f, UnitPixel, &attributes);
                        if (status != Ok) {
                            printf("draw_error=%d case=%u\n", status, cases);
                            return 5;
                        }
                        BitmapData locked;
                        Rect rect(0, 0, dw, dh);
                        if (target.LockBits(&rect, ImageLockModeRead, PixelFormat32bppARGB, &locked) != Ok)
                            return 6;
                        for (int y = 0; y < dh; y++)
                            fwrite((BYTE*)locked.Scan0 + y * locked.Stride, 1, dw * 4, output);
                        target.UnlockBits(&locked);
                        cases++;
                    }
    }
    fclose(output);
    printf("cases=%u\n", cases);
    std::vector<ARGB> large(942 * 810);
    for (ARGB& p : large)
        p = next_pixel() | 0xff000000;
    {
        Bitmap source(942, 810, 942 * 4, PixelFormat32bppARGB, (BYTE*)large.data());
        Bitmap target(1884, 1620, PixelFormat32bppARGB);
        Graphics graphics(&target);
        graphics.SetInterpolationMode(InterpolationModeHighQualityBicubic);
        double start = now();
        for (int i = 0; i < 8; i++)
            if (graphics.DrawImage(&source, 0, 0, 1884, 1620) != Ok)
                return 7;
        printf("eight_2x_draw_ms=%.3f\n", (now() - start) * 1000);
    }
    GdiplusShutdown(token);
    return 0;
}
